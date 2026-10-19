"""O-RAN Security Digital Twin: time-stepped network simulator with a security layer.

Per tick (dt seconds):
  mobility -> shadowing -> RSRP -> cell selection / A3 handover (security re-selection at
  target gNB, TS 33.501 6.7.3.1) -> SINR with load-weighted interference -> water-filling
  scheduler per cell -> per-UE throughput, goodput (PDCP/MAC-I overhead), latency -> attacks
  -> exposure accounting -> config drift -> SMO compliance service -> remediation pushes.

Every site (gNB, 3 sectors) carries a full OAI-style configuration file. The security
algorithms each UE gets are computed from that file, so a misconfiguration has concrete
consequences: null ciphering, spoofable RRC, attach failures, intercepted traffic.
"""
from __future__ import annotations

import copy
import json
import math
from collections import deque
from dataclasses import dataclass, field, asdict

import numpy as np

from ..conf.patch import apply_fixes
from ..conf.security import (CIPHER_ALGS, INTEG_ALGS, Profile, evaluate, security_view, summarize)
from ..conf.template import GnbIdentity, SecuritySettings, render
from .radio import RadioMap, full_rate_bps, hex_sites
from .traffic import DEFAULT_MIX, HDR_BYTES, MAC_I_BYTES, TrafficState, diurnal

# UE capability classes: (cipher set, integrity set, share). All UEs implement NEA0/NIA0.
CAP_CLASSES = [({0, 1, 2}, {0, 1, 2}), ({0, 1, 2, 3}, {0, 1, 2, 3})]

HO_HYST_DB = 4.0        # A3 offset 3 dB + hysteresis 1 dB
TTT_S = 0.32
L3_ALPHA = 0.25         # layer-3 RSRP filter per 1 s tick (approx. filterCoefficient k=8 at 200 ms)
HO_INTERRUPT_MS = 30.0
BASE_LAT_MS = 1.0 + 0.8 + 3.0 + 1.0      # air (TTI+proc) + HARQ + backhaul + core
UP_INTEG_PROC_MS = 0.05
IPSEC_PROC_MS = 0.10
RLF_SINR_DB = -8.0      # Qout
T310_S = 1.0


@dataclass
class Attacker:
    kind: str                 # sniffer | rrc_injector | backhaul_tap | o1_mitm
    x: float = 0.0
    y: float = 0.0
    radius: float = 350.0
    site: int = -1
    rate_per_hour: float = 2.0  # o1_mitm config-injection attempts per hour per vulnerable site
    attempt_period_s: float = 30.0


@dataclass
class ScenarioConfig:
    n_sites: int = 19
    isd: float = 500.0
    n_ues: int = 1500
    mobility: dict = field(default_factory=lambda: {"static": 0.3, "pedestrian": 0.5, "vehicular": 0.2})
    traffic_mix: dict = field(default_factory=lambda: dict(DEFAULT_MIX))
    cap_class_share: float = 0.3          # share of UEs that also implement NEA3/NIA3
    nonconformant_nia0_share: float = 0.2  # basebands that accept an SMC selecting NIA0 (scenario assumption)
    dt: float = 1.0
    start_hour: float = 18.0
    seed: int = 1
    profile: dict = field(default_factory=lambda: {"emergency_unauth_supported": False,
                                                   "baseline": "operator_hardened"})
    drift_rate_per_site_hour: float = 0.15
    attackers: list = field(default_factory=list)
    # SMO compliance service
    arm: str = "A5"
    detection: str = "notify"           # notify (O1 change notification) | poll
    poll_interval_s: float = 900.0
    approval_delay_s: float = 120.0
    remediation_policy: str = "immediate"   # immediate | window | rl | none
    window_hours: tuple = (2.0, 4.0)
    outage_algo_s: float = 20.0
    outage_iface_s: float = 5.0
    audit_interval_h: float = 24.0
    telemetry_every_s: float = 10.0


class Site:
    def __init__(self, idx: int, ident: GnbIdentity, text: str, item_id: str | None):
        self.idx = idx
        self.ident = ident
        self.text = text
        self.item_id = item_id
        self.approved_hash = hash(text)
        self.outage_until = -1.0
        self.violations: list[str] = []
        self.compliant = True
        self.drift_t: float | None = None     # time the current non-compliance started
        self.detected_t: float | None = None
        self.sel_c = np.zeros(len(CAP_CLASSES), dtype=int)
        self.sel_i = np.zeros(len(CAP_CLASSES), dtype=int)
        self.drb_c = True
        self.drb_i = False
        self.iface = {}

    def on_air(self, t):
        return t >= self.outage_until


class Twin:
    def __init__(self, cfg: ScenarioConfig, dataset: list[dict] | None = None, agent=None, policy=None):
        self.cfg = cfg
        self.rng = np.random.default_rng(cfg.seed)
        self.ev_rng = np.random.default_rng([cfg.seed, 99])      # config-change events only
        self.profile = Profile(**cfg.profile)
        self.t = 0.0
        self.tick = 0
        self.dataset = dataset or []
        self.pool = [d for d in self.dataset if Profile(**d["profile"]) == self.profile]
        self.agent = agent          # SMO compliance service (twin.smo.ComplianceService)
        self.policy = policy        # remediation policy (twin.smo / rl)
        self.events: deque = deque(maxlen=400)
        self.event_log: list[dict] = []

        # ------------------------------------------------------------- sites
        xy = hex_sites(cfg.n_sites, cfg.isd)
        self.radio = RadioMap(xy, self.rng)
        self.sites: list[Site] = []
        for s in range(cfg.n_sites):
            ident = GnbIdentity(gnb_id=0xE00 + s, name=f"gNB-{s:03d}", nr_cellid=12345000 + 16 * s,
                                pci=(3 * s) % 1008, vendor=["oai", "vendorA", "vendorB", "vendorC"][s % 4])
            from ..dataset.generate import SECURE
            text = render(ident, SecuritySettings(**SECURE))
            self.sites.append(Site(s, ident, text, None))
            self._load_site_security(self.sites[-1])

        # ------------------------------------------------------------- UEs
        n = cfg.n_ues
        self.n = n
        r_cell = cfg.isd / math.sqrt(3)
        self.bounds = np.array([xy[:, 0].min() - r_cell, xy[:, 0].max() + r_cell,
                                xy[:, 1].min() - r_cell, xy[:, 1].max() + r_cell])
        self.ue_xy = self._sample_points(n)
        mob = cfg.mobility
        kinds = self.rng.choice(3, size=n, p=np.array([mob["static"], mob["pedestrian"], mob["vehicular"]]) /
                                sum(mob.values()))
        self.speed = np.where(kinds == 0, 0.0, np.where(kinds == 1, self.rng.uniform(0.8, 1.8, n),
                                                          self.rng.uniform(8, 17, n)))
        self.mob_kind = kinds
        self.target = self._sample_points(n)
        self.pause_until = np.zeros(n)
        self.radio.init_shadow(n)
        self.traffic = TrafficState(n, cfg.traffic_mix, self.rng)
        self.cap = (self.rng.random(n) < cfg.cap_class_share).astype(int)
        self.accepts_nia0 = self.rng.random(n) < cfg.nonconformant_nia0_share
        self.serving = -np.ones(n, dtype=int)
        self.ttt = np.zeros(n)
        self.backlog = np.zeros(n)
        self.denied_until = np.zeros(n)
        self.up_c = np.zeros(n, dtype=int)      # selected UP ciphering alg idx, -1 = off
        self.up_i = -np.ones(n, dtype=int)
        self.rrc_i = np.zeros(n, dtype=int)
        self.cell_load = np.full(self.radio.n_cells, 0.3)
        self.rx_f = None
        self.low_s = np.zeros(n)
        self.rlf_state = np.zeros(n, dtype=bool)
        self.last_tput = np.zeros(n)
        self.last_lat = np.full(n, BASE_LAT_MS)
        self.last_sinr = np.zeros(n)
        self.attackers = [Attacker(**a) if isinstance(a, dict) else a for a in cfg.attackers]
        self.next_audit = cfg.audit_interval_h * 3600.0
        self.pending_pushes: list[dict] = []
        self._dg_pending: dict[int, int] = {}
        self._dg_last: dict[int, float] = {}

        # ------------------------------------------------------------- accounting
        self.acc = dict(ue_seconds=0.0, ue_seconds_served=0.0, unciphered_ue_s=0.0, spoofable_ue_s=0.0,
                        bits_delivered=0.0, goodput_bits=0.0, bits_unciphered=0.0, bits_intercepted=0.0,
                        attack_attempts=0, attack_success=0, attack_blocked=0, attach_fail_ue_s=0.0,
                        outage_ue_s=0.0, denied_ue_s=0.0, handovers=0, downgrades_at_ho=0, rlf=0,
                        drift_events=0, malicious_injections=0, pushes=0, unnecessary_pushes=0,
                        missed=0, detections=0, noncompliant_site_s=0.0, lat_samples=[], ttd=[], ttr=[],
                        served_app=np.zeros(6), goodput_app=np.zeros(6),
                        remediation_reselections=0, remediation_ue_s=0.0)
        self.tele_cells: list[list] = []
        self.tele_sites: list[list] = []
        self.tele_net: list[dict] = []
        self._next_tele = 0.0

    # ================================================================= helpers
    @property
    def hour(self) -> float:
        return (self.cfg.start_hour + self.t / 3600.0) % 24.0

    def _sample_points(self, n):
        out = np.empty((0, 2))
        r_cell = self.cfg.isd / math.sqrt(3)
        while len(out) < n:
            p = np.column_stack([self.rng.uniform(self.bounds[0], self.bounds[1], 2 * n),
                                 self.rng.uniform(self.bounds[2], self.bounds[3], 2 * n)])
            d = np.min(np.hypot(p[:, None, 0] - self.radio.site_xy[None, :, 0],
                                p[:, None, 1] - self.radio.site_xy[None, :, 1]), axis=1)
            out = np.vstack([out, p[d < r_cell * 0.95]])
        return out[:n]

    def log(self, kind: str, site: int | None = None, **kw):
        e = {"t": round(self.t, 1), "hour": round(self.hour, 3), "kind": kind, "site": site, **kw}
        self.events.append(e)
        self.event_log.append(e)

    def _load_site_security(self, site: Site):
        sec = security_view(site.text)
        ca = [CIPHER_ALGS.index(a) for a in (sec.get("ciphering_algorithms") or []) if a in CIPHER_ALGS]
        ia = [INTEG_ALGS.index(a) for a in (sec.get("integrity_algorithms") or []) if a in INTEG_ALGS]
        for k, (cs, is_) in enumerate(CAP_CLASSES):
            site.sel_c[k] = next((a for a in ca if a in cs), -2)
            site.sel_i[k] = next((a for a in ia if a in is_), -2)
        site.drb_c = str(sec.get("drb_ciphering")).lower() != "no"
        site.drb_i = str(sec.get("drb_integrity")).lower() == "yes"
        site.iface = {k: sec.get(k) for k in ("f1c_protection", "n2_protection", "n3_protection", "xn_protection",
                                               "e2_protection", "o1_transport", "tls_min_version")}
        labels = evaluate(sec, self.profile)
        s = summarize(labels)
        was = site.compliant
        site.violations = s["violations"]
        site.compliant = s["compliant"]
        if was and not site.compliant:
            site.drift_t = self.t
            site.detected_t = None
        if not was and site.compliant and site.drift_t is not None:
            self.acc["ttr"].append(self.t - site.drift_t)
            site.drift_t = None

    def site_compat(self) -> np.ndarray:
        """UE x site: can the UE obtain AS security at this site?"""
        out = np.zeros((self.n, len(self.sites)), dtype=bool)
        for s in self.sites:
            ok_c = s.sel_c[self.cap] >= 0
            si = s.sel_i[self.cap]
            ok_i = (si > 0) | ((si == 0) & self.accepts_nia0)   # conformant UEs reject an SMC selecting NIA0
            out[:, s.idx] = ok_c & ok_i & s.on_air(self.t)
        return out

    def _assign_security(self, ues: np.ndarray):
        for u in ues:
            c = self.serving[u]
            if c < 0:
                continue
            s = self.sites[self.radio.cell_site[c]]
            k = self.cap[u]
            self.rrc_i[u] = s.sel_i[k]
            self.up_c[u] = s.sel_c[k] if s.drb_c else -1
            self.up_i[u] = s.sel_i[k] if (s.drb_i and s.sel_i[k] > 0) else -1

    # ================================================================= main step
    def step(self):
        cfg, dt, n = self.cfg, self.cfg.dt, self.n
        load_f = diurnal(self.hour)

        # ---- mobility (random waypoint with pauses)
        moving = (self.speed > 0) & (self.t >= self.pause_until)
        vec = self.target - self.ue_xy
        dist = np.hypot(vec[:, 0], vec[:, 1])
        step_len = np.where(moving, np.minimum(self.speed * dt, dist), 0.0)
        with np.errstate(invalid="ignore", divide="ignore"):
            unit = np.where(dist[:, None] > 0, vec / dist[:, None], 0.0)
        self.ue_xy = self.ue_xy + unit * step_len[:, None]
        arrived = moving & (dist - step_len < 1.0)
        if arrived.any():
            idx = np.where(arrived)[0]
            self.target[idx] = self._sample_points(len(idx))
            self.pause_until[idx] = self.t + self.rng.exponential(20.0, len(idx))
        moved_rows = self.radio.update_shadow(step_len)

        # ---- traffic
        self.traffic.step(dt, load_f)
        self.backlog += self.traffic.demand_bits(dt)
        cap = self.traffic.rate * (self.traffic.buffer_s + dt)
        self.dropped_bits = np.maximum(self.backlog - cap, 0.0)
        self.backlog = np.minimum(self.backlog, cap)

        # ---- cell selection, handover, security (re-)selection
        raw = self.radio.rsrp(self.ue_xy, None if self.rx_f is None else moved_rows)
        self.rx_f = raw.copy() if self.rx_f is None else (1 - L3_ALPHA) * self.rx_f + L3_ALPHA * raw
        rx = self.rx_f
        compat = self.site_compat()[:, self.radio.cell_site]           # UE x cell
        denied = self.t < self.denied_until
        rx_ok = np.where(compat, rx, -np.inf)
        best = np.argmax(rx_ok, axis=1)
        best_rx = rx_ok[np.arange(n), best]
        has_best = np.isfinite(best_rx)
        cur = self.serving
        cur_ok = (cur >= 0) & compat[np.arange(n), np.maximum(cur, 0)]
        cur_rx = np.where(cur_ok, rx[np.arange(n), np.maximum(cur, 0)], -np.inf)
        # forced reselection: lost cell (outage / became incompatible / attach)
        forced = (~cur_ok) & has_best & ~denied
        ho_cand = cur_ok & (best != cur) & (best_rx > cur_rx + HO_HYST_DB)
        self.ttt = np.where(ho_cand, self.ttt + dt, 0.0)
        do_ho = ho_cand & (self.ttt >= TTT_S)
        changed = np.where(forced | do_ho)[0]
        prev_upc = self.up_c.copy()
        self.serving = np.where(forced | do_ho, best, self.serving)
        self.serving = np.where(~has_best | denied, -1, self.serving)
        self.ttt[changed] = 0.0
        self._assign_security(changed)
        n_ho = int(do_ho.sum())
        self.acc["handovers"] += n_ho
        if n_ho:
            ho_idx = np.where(do_ho)[0]
            down = ho_idx[(prev_upc[ho_idx] > 0) & (self.up_c[ho_idx] <= 0)]
            if len(down):
                self.acc["downgrades_at_ho"] += len(down)
                for u in down:
                    sid = int(self.radio.cell_site[self.serving[u]])
                    self._dg_pending[sid] = self._dg_pending.get(sid, 0) + 1
        for sid in list(self._dg_pending):
            if self.t - self._dg_last.get(sid, -1e9) >= 30.0:      # aggregate log lines per site per 30 s
                self.log("downgrade_at_handover", sid, ues=self._dg_pending.pop(sid))
                self._dg_last[sid] = self.t

        serving = self.serving
        connected = serving >= 0
        # ---- SINR and rates
        cell_on = np.array([self.sites[s].on_air(self.t) for s in self.radio.cell_site], dtype=float)
        sinr = self.radio.sinr(rx, serving, self.cell_load, cell_on)
        sinr = np.where(connected, sinr, -30.0)
        low = connected & (sinr < RLF_SINR_DB)
        self.low_s = np.where(low, self.low_s + dt, np.where(sinr > RLF_SINR_DB + 3.0, 0.0, self.low_s))
        rlf = low & (self.low_s > T310_S) & ~self.rlf_state   # out-of-sync longer than T310 -> RLF
        self.acc["rlf"] += int(rlf.sum())
        self.rlf_state = (self.rlf_state | rlf) & (sinr < RLF_SINR_DB + 3.0)   # until Qin (Qout + 3 dB) recovery
        r_full = np.where(connected & ~rlf, full_rate_bps(sinr), 0.0)

        # ---- scheduler: water-filling of time shares per cell
        alloc = np.zeros(n)
        new_load = np.zeros(self.radio.n_cells)
        need = self.backlog / dt
        for c in np.unique(serving[connected]):
            ues = np.where((serving == c) & (r_full > 0))[0]
            if len(ues) == 0:
                continue
            share_need = np.minimum(need[ues] / r_full[ues], 1.0)
            order = np.argsort(share_need)
            remaining, left = 1.0, len(ues)
            shares = np.zeros(len(ues))
            for j in order:
                fair = remaining / left
                shares[j] = min(share_need[j], fair)
                remaining -= shares[j]
                left -= 1
            alloc[ues] = shares * r_full[ues]
            new_load[c] = 1.0 - remaining
        self.cell_load = 0.7 * self.cell_load + 0.3 * new_load

        served = np.minimum(self.backlog, alloc * dt)
        ho_now = np.zeros(n, dtype=bool)
        ho_now[changed] = True
        served = np.where(ho_now, served * max(0.0, 1 - HO_INTERRUPT_MS / 1000.0 / dt), served)
        self.backlog -= served
        pkt = self.traffic.pkt
        hdr = HDR_BYTES + np.where(self.up_i > 0, MAC_I_BYTES, 0)
        goodput = served * pkt / (pkt + hdr)

        # ---- latency (ms)
        site_of = np.where(connected, self.radio.cell_site[np.maximum(serving, 0)], -1)
        ipsec = np.array([1.0 if str(s.iface.get("n3_protection")) == "ipsec" else 0.0 for s in self.sites])
        with np.errstate(divide="ignore", invalid="ignore"):
            q_ms = np.where(alloc > 0, np.minimum(self.backlog / np.maximum(alloc, 1.0) * 1000.0,
                                                  self.traffic.buffer_s * 1000.0), self.traffic.buffer_s * 1000.0)
        lat = (BASE_LAT_MS + q_ms + np.where(self.up_i > 0, UP_INTEG_PROC_MS, 0.0)
               + np.where(site_of >= 0, ipsec[np.maximum(site_of, 0)] * IPSEC_PROC_MS, 0.0)
               + np.where(ho_now, HO_INTERRUPT_MS, 0.0))
        active = self.traffic.active & connected
        self.last_tput = np.where(connected, served / dt, 0.0)
        self.last_lat = lat
        self.last_sinr = sinr
        if self.tick % 5 == 0 and active.any():
            self.acc["lat_samples"].extend(np.round(lat[active], 2).tolist()[:400])

        # ---- exposure
        unciph = connected & (self.up_c <= 0)
        spoof = connected & (self.rrc_i == 0)
        self.acc["ue_seconds"] += n * dt
        self.acc["ue_seconds_served"] += connected.sum() * dt
        self.acc["unciphered_ue_s"] += float(unciph[self.traffic.active].sum()) * dt
        self.acc["spoofable_ue_s"] += float(spoof.sum()) * dt
        self.acc["bits_delivered"] += float(served.sum())
        self.acc["goodput_bits"] += float(goodput.sum())
        self.acc["served_app"] += np.bincount(self.traffic.app, weights=served, minlength=6)
        self.acc["goodput_app"] += np.bincount(self.traffic.app, weights=goodput, minlength=6)
        self.acc["bits_unciphered"] += float(served[unciph].sum())
        no_service = (~connected) & ~denied
        outage_sites = {s.idx for s in self.sites if not s.on_air(self.t)}
        if outage_sites:
            near = np.argmax(rx, axis=1)
            in_out = np.isin(self.radio.cell_site[near], list(outage_sites))
            self.acc["outage_ue_s"] += float((no_service & in_out).sum()) * dt
            self.acc["attach_fail_ue_s"] += float((no_service & ~in_out).sum()) * dt
        else:
            self.acc["attach_fail_ue_s"] += float(no_service.sum()) * dt
        self.acc["denied_ue_s"] += float(denied.sum()) * dt
        nc = sum(1 for s in self.sites if not s.compliant)
        self.acc["noncompliant_site_s"] += nc * dt

        # ---- attacks
        self._attacks(served, unciph, spoof, connected, site_of, dt)
        # ---- config drift
        self._drift(dt)
        # ---- SMO compliance service and remediation
        if self.agent is not None:
            self.agent.tick(self)
        self._process_pushes()
        if self.t >= self.next_audit:
            self._audit()
            self.next_audit += self.cfg.audit_interval_h * 3600.0
        # ---- telemetry
        if self.t >= self._next_tele:
            self._telemetry(served, sinr, lat, connected, unciph, spoof)
            self._next_tele += cfg.telemetry_every_s
        self.t += dt
        self.tick += 1

    # ================================================================= attacks
    def _attacks(self, served, unciph, spoof, connected, site_of, dt):
        for a in self.attackers:
            if a.kind == "sniffer":
                d = np.hypot(self.ue_xy[:, 0] - a.x, self.ue_xy[:, 1] - a.y)
                caught = (d < a.radius) & unciph
                self.acc["bits_intercepted"] += float(served[caught].sum())
            elif a.kind == "rrc_injector":
                d = np.hypot(self.ue_xy[:, 0] - a.x, self.ue_xy[:, 1] - a.y)
                tgt = (d < a.radius) & connected & (self.rng.random(self.n) < dt / a.attempt_period_s)
                if not tgt.any():
                    continue
                ok = tgt & spoof
                blocked = tgt & ~spoof
                self.acc["attack_attempts"] += int(tgt.sum())
                self.acc["attack_success"] += int(ok.sum())
                self.acc["attack_blocked"] += int(blocked.sum())
                if ok.any():
                    idx = np.where(ok)[0]
                    self.denied_until[idx] = self.t + 15.0
                    self.serving[idx] = -1
                    self.log("rrc_injection_success", int(site_of[idx[0]]), ues=int(len(idx)))
            elif a.kind == "backhaul_tap" and 0 <= a.site < len(self.sites):
                s = self.sites[a.site]
                if str(s.iface.get("n3_protection")) == "none":
                    self.acc["bits_intercepted"] += float(served[site_of == a.site].sum())
            elif a.kind == "o1_mitm":
                u = self.ev_rng.random(len(self.sites))      # fixed number of draws per tick
                for s in self.sites:
                    if str(s.iface.get("o1_transport")) == "netconf_plain" and u[s.idx] < a.rate_per_hour * dt / 3600.0:
                        self._inject_config(s, malicious=True)

    # ================================================================= drift
    def _pick_item(self, noncompliant_only=False, key=0):
        """Deterministic per (seed, tick, key) so every arm sees the same event sequence
        (common random numbers), independent of what the agent did earlier."""
        pool = self.pool or self.dataset
        if noncompliant_only:
            p2 = [d for d in pool if not d["summary"]["compliant"]]
            pool = p2 or pool
        g = np.random.default_rng([self.cfg.seed, self.tick, key, 7])
        return pool[int(g.integers(len(pool)))] if pool else None

    def _inject_config(self, site: Site, malicious=False):
        it = self._pick_item(noncompliant_only=malicious, key=site.idx * 2 + int(malicious))
        if it is None:
            return
        site.text = render(site.ident, SecuritySettings(**it["settings"]))
        site.item_id = it["id"]
        self._load_site_security(site)
        self.acc["drift_events"] += 1
        if malicious:
            self.acc["malicious_injections"] += 1
        self.log("config_change", site.idx, item=it["id"], cause="o1_mitm" if malicious else "vendor/rApp push",
                 compliant=site.compliant, violations=site.violations)
        # UEs on this site keep their AS context until next (re)selection; new attaches use new config
        on_site = np.where((self.serving >= 0) & (self.radio.cell_site[np.maximum(self.serving, 0)] == site.idx))[0]
        self._assign_security(on_site)
        if self.agent is not None:
            self.agent.notify_change(self, site)

    def _drift(self, dt):
        lam = self.cfg.drift_rate_per_site_hour * dt / 3600.0
        u = self.ev_rng.random(len(self.sites))
        for s in self.sites:
            if u[s.idx] < lam:
                self._inject_config(s)

    # ================================================================= remediation
    def schedule_push(self, site_idx: int, fixes: dict, ready_t: float, source: str, run: dict | None = None):
        self.pending_pushes.append({"site": site_idx, "fixes": fixes, "ready_t": ready_t, "source": source,
                                    "created_t": self.t, "run": run or {}})

    def _process_pushes(self):
        keep = []
        for p in self.pending_pushes:
            if self.t < p["ready_t"]:
                keep.append(p)
                continue
            if self.policy is not None and not self.policy.allow(self, p):
                keep.append(p)
                continue
            self.push(p["site"], p["fixes"], p["source"])
        self.pending_pushes = keep

    def push(self, site_idx: int, fixes: dict, source: str):
        s = self.sites[site_idx]
        was_compliant = s.compliant
        new_text, errs = apply_fixes(s.text, fixes)
        algo = any(k in fixes for k in ("ciphering_algorithms", "integrity_algorithms", "drb_ciphering", "drb_integrity"))
        outage = self.cfg.outage_algo_s if algo else self.cfg.outage_iface_s
        s.outage_until = self.t + outage
        on_site = int(((self.serving >= 0) & (self.radio.cell_site[np.maximum(self.serving, 0)] == site_idx)).sum())
        self.acc["remediation_reselections"] += on_site      # UEs forced off the gNB while it restarts
        self.acc["remediation_ue_s"] += on_site * outage
        s.text = new_text
        s.item_id = None
        s.approved_hash = hash(new_text)
        self._load_site_security(s)
        self.acc["pushes"] += 1
        if was_compliant:
            self.acc["unnecessary_pushes"] += 1
        self.log("remediation_push", site_idx, source=source, fixes=fixes, outage_s=outage,
                 compliant_after=s.compliant, violations_after=s.violations)

    def _audit(self):
        """Periodic human audit: fixes any remaining non-compliance with the minimal repair."""
        from ..repair.smt import optimal_repair
        for s in self.sites:
            if not s.compliant:
                r = optimal_repair(s.text, self.profile)
                self.acc["missed"] += 1
                self.log("manual_audit_fix", s.idx, violations=s.violations)
                self.push(s.idx, r["fixes"], "manual_audit")

    # ================================================================= telemetry
    def _telemetry(self, served, sinr, lat, connected, unciph, spoof):
        cs = self.radio.cell_site
        srv = self.serving
        t = round(self.t, 1)
        for c in range(self.radio.n_cells):
            m = srv == c
            k = int(m.sum())
            self.tele_cells.append([t, c, int(cs[c]), k, round(float(self.cell_load[c]), 3),
                                    round(float(served[m].sum() / self.cfg.dt / 1e6), 3),
                                    round(float(np.mean(sinr[m])) if k else 0.0, 2),
                                    round(float(np.percentile(lat[m], 95)) if k else 0.0, 2),
                                    int((m & unciph).sum()), int((m & spoof).sum())])
        for s in self.sites:
            self.tele_sites.append([t, s.idx, int(s.compliant), len(s.violations), int(s.on_air(self.t)),
                                    s.item_id or ""])
        act = self.traffic.active & connected
        self.tele_net.append({
            "t": t, "hour": round(self.hour, 3), "connected": int(connected.sum()),
            "dl_gbps": round(float(served.sum() / self.cfg.dt / 1e9), 4),
            "lat_p50": round(float(np.percentile(lat[act], 50)), 2) if act.any() else 0,
            "lat_p95": round(float(np.percentile(lat[act], 95)), 2) if act.any() else 0,
            "unciphered": int((unciph & self.traffic.active).sum()), "spoofable": int(spoof.sum()),
            "noncompliant_sites": sum(1 for s in self.sites if not s.compliant),
            "sites_off_air": sum(1 for s in self.sites if not s.on_air(self.t)),
            "attack_success": self.acc["attack_success"], "intercepted_gb": round(self.acc["bits_intercepted"] / 8e9, 4),
            "load": round(diurnal(self.hour), 3)})

    # ================================================================= export
    def export(self, out_dir) -> dict:
        """Write the run's telemetry as a Parquet dataset (cell KPIs, site state, network KPIs, events)."""
        import pandas as pd
        from pathlib import Path
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        cells = pd.DataFrame(self.tele_cells, columns=["t_s", "cell", "site", "ues", "prb_load", "dl_mbps",
                                                       "mean_sinr_db", "lat_p95_ms", "unciphered_ues", "spoofable_ues"])
        sites = pd.DataFrame(self.tele_sites, columns=["t_s", "site", "compliant", "n_violations", "on_air", "config_item"])
        net = pd.DataFrame(self.tele_net)
        ev = pd.DataFrame([{k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in e.items() if k != "run"}
                           for e in self.event_log])
        files = {}
        for name, df in (("cell_kpi", cells), ("site_state", sites), ("network_kpi", net), ("events", ev)):
            f = out / f"{name}.parquet"
            df.to_parquet(f, index=False)
            files[name] = {"path": str(f), "rows": len(df)}
        meta = {"scenario": asdict(self.cfg), "summary": self.summary(), "files": files}
        (out / "run.json").write_text(json.dumps(meta, indent=1, default=float))
        return meta

    # ================================================================= reporting
    def summary(self) -> dict:
        a = self.acc
        lat = np.array(a["lat_samples"]) if a["lat_samples"] else np.array([0.0])
        hrs = self.t / 3600.0
        return {
            "sim_hours": round(hrs, 3),
            "throughput_gbps_mean": round(a["bits_delivered"] / max(self.t, 1) / 1e9, 4),
            "goodput_ratio": round(a["goodput_bits"] / max(a["bits_delivered"], 1), 5),
            "latency_p50_ms": round(float(np.percentile(lat, 50)), 2),
            "latency_p95_ms": round(float(np.percentile(lat, 95)), 2),
            "latency_p99_ms": round(float(np.percentile(lat, 99)), 2),
            "service_availability": round(a["ue_seconds_served"] / max(a["ue_seconds"], 1), 5),
            "unciphered_active_ue_hours": round(a["unciphered_ue_s"] / 3600, 3),
            "spoofable_ue_hours": round(a["spoofable_ue_s"] / 3600, 3),
            "gb_unciphered": round(a["bits_unciphered"] / 8e9, 3),
            "gb_intercepted": round(a["bits_intercepted"] / 8e9, 3),
            "attack_attempts": a["attack_attempts"], "attack_success": a["attack_success"],
            "attack_success_rate": round(a["attack_success"] / max(a["attack_attempts"], 1), 4),
            "attach_fail_ue_hours": round(a["attach_fail_ue_s"] / 3600, 3),
            "remediation_outage_ue_hours": round(a["outage_ue_s"] / 3600, 3),
            "remediation_reselections": a["remediation_reselections"],
            "remediation_displaced_ue_hours": round(a["remediation_ue_s"] / 3600, 3),
            "denied_ue_hours": round(a["denied_ue_s"] / 3600, 3),
            "handovers": a["handovers"], "downgrades_at_handover": a["downgrades_at_ho"], "rlf": a["rlf"],
            "drift_events": a["drift_events"], "malicious_injections": a["malicious_injections"],
            "detections": a["detections"], "pushes": a["pushes"], "unnecessary_pushes": a["unnecessary_pushes"],
            "missed_until_audit": a["missed"],
            "noncompliant_site_hours": round(a["noncompliant_site_s"] / 3600, 3),
            "mttd_s": round(float(np.mean(a["ttd"])), 1) if a["ttd"] else None,
            "mttr_s": round(float(np.mean(a["ttr"])), 1) if a["ttr"] else None,
        }

    def snapshot(self, max_ues: int = 2500) -> dict:
        n = min(self.n, max_ues)
        site_of = np.where(self.serving >= 0, self.radio.cell_site[np.maximum(self.serving, 0)], -1)
        flags = ((self.up_c <= 0) & (self.serving >= 0)).astype(int) + \
                2 * ((self.rrc_i == 0) & (self.serving >= 0)).astype(int) + \
                4 * (self.t < self.denied_until).astype(int) + 8 * (self.serving < 0).astype(int)
        return {
            "t": round(self.t, 1), "hour": round(self.hour, 3),
            "ues": {"x": np.round(self.ue_xy[:n, 0], 1).tolist(), "y": np.round(self.ue_xy[:n, 1], 1).tolist(),
                    "site": site_of[:n].tolist(), "cell": self.serving[:n].tolist(), "flags": flags[:n].tolist(),
                    "tput": np.round(self.last_tput[:n] / 1e6, 2).tolist(), "app": self.traffic.app[:n].tolist(),
                    "active": self.traffic.active[:n].astype(int).tolist()},
            "sites": [{"idx": s.idx, "name": s.ident.name, "vendor": s.ident.vendor,
                       "x": float(self.radio.site_xy[s.idx, 0]), "y": float(self.radio.site_xy[s.idx, 1]),
                       "compliant": s.compliant, "violations": s.violations, "on_air": s.on_air(self.t),
                       "item": s.item_id, "load": [round(float(x), 3) for x in self.cell_load[3 * s.idx:3 * s.idx + 3]],
                       "ues": int((site_of == s.idx).sum()),
                       "sel_c": [CIPHER_ALGS[i] if i >= 0 else None for i in s.sel_c],
                       "sel_i": [INTEG_ALGS[i] if i >= 0 else None for i in s.sel_i],
                       "drb_c": s.drb_c, "drb_i": s.drb_i, "iface": s.iface} for s in self.sites],
            "attackers": [asdict(a) for a in self.attackers],
            "bounds": self.bounds.tolist(), "isd": self.cfg.isd,
            "net": self.tele_net[-1] if self.tele_net else {},
            "summary": self.summary(),
        }
