"""Twin experiments.

E4  closed loop: the same 6-hour scenario (same drift and attack sequence) run with each agent
    configuration as the SMO compliance service, in replay mode (measured outcome and latency per
    config from E1). Plus remediation-policy comparison for A5.
E5  cost of security features at busy hour: user-plane integrity on/off, N3 IPsec on/off,
    urban and VoIP-heavy traffic.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

from ..conf.template import SecuritySettings, render
from ..dataset.generate import SECURE
from ..twin.engine import ScenarioConfig, Twin
from ..twin.smo import ComplianceService, ImmediatePolicy, NoRemediation, WindowPolicy, load_replay
from ..twin.traffic import APP_NAMES

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "results"


def _set_all(tw: Twin, **over):
    for s in tw.sites:
        st = dict(SECURE)
        st.update(over)
        s.text = render(s.ident, SecuritySettings(**st))
        tw._load_site_security(s)


def e5(minutes=20):
    rows = []
    cases = [
        ("Baseline (UP integrity off, N3 IPsec)", "urban", {}),
        ("UP integrity on", "urban", {"drb_integrity": "yes"}),
        ("N3 IPsec off", "urban", {"n3_protection": "none"}),
        ("VoIP-heavy, UP integrity off", "voip", {}),
        ("VoIP-heavy, UP integrity on", "voip", {"drb_integrity": "yes"}),
    ]
    mixes = {"urban": None, "voip": {"video": 0.2, "web": 0.2, "voip": 0.45, "iot": 0.1, "bulk": 0.03, "fwa": 0.02}}
    for name, mix, over in cases:
        cfg = ScenarioConfig(n_sites=19, n_ues=1500, start_hour=19.0, seed=5, drift_rate_per_site_hour=0.0)
        if mixes[mix]:
            cfg.traffic_mix = mixes[mix]
        tw = Twin(cfg, [])
        _set_all(tw, **over)
        for _ in range(int(minutes * 60 / cfg.dt)):
            tw.step()
        s = tw.summary()
        v = APP_NAMES.index("voip")
        sa, ga = tw.acc["served_app"], tw.acc["goodput_app"]
        rows.append({"name": name, "goodput_ratio": s["goodput_ratio"],
                     "voip_overhead": float(1 - ga[v] / sa[v]) if sa[v] else 0.0,
                     "latency_p50_ms": s["latency_p50_ms"], "latency_p95_ms": s["latency_p95_ms"],
                     "latency_p99_ms": s["latency_p99_ms"], "throughput_gbps": s["throughput_gbps_mean"]})
        print(rows[-1], flush=True)
    out = {"rows": rows, "minutes": minutes,
           "note": "Busy hour (19:00), 19 sites, 1500 UEs. Integrity overhead = 4-byte MAC-I per PDCP PDU plus "
                   "0.05 ms processing; IPsec = 0.1 ms per packet. Ciphering cost is not modelled."}
    (RES / "e5_cost.json").write_text(json.dumps(out, indent=1))
    return out


def _scenario(arm_policy_seed=3):
    return ScenarioConfig(
        n_sites=19, n_ues=1500, start_hour=16.0, seed=arm_policy_seed,
        profile={"emergency_unauth_supported": True, "baseline": "operator_hardened"},
        drift_rate_per_site_hour=0.5, approval_delay_s=120.0, audit_interval_h=24.0,
        attackers=[{"kind": "sniffer", "x": 0, "y": 0, "radius": 380},
                   {"kind": "rrc_injector", "x": 500, "y": 300, "radius": 330},
                   {"kind": "o1_mitm", "rate_per_hour": 1.0}])


def run_closed_loop(arm: str | None, policy: str, hours: float, data, replay):
    cfg = _scenario()
    agent = None if arm is None else ComplianceService(arm, mode="replay", replay=replay, pipeline=None,
                                                       approval_delay_s=cfg.approval_delay_s)
    pol = {"immediate": ImmediatePolicy(), "window": WindowPolicy(), "none": NoRemediation()}.get(policy)
    if policy == "rl":
        from ..rl.policy import RLPolicy
        pol = RLPolicy.load()
    tw = Twin(cfg, data, agent=agent, policy=pol)
    t0 = time.time()
    for _ in range(int(hours * 3600 / cfg.dt)):
        tw.step()
    s = tw.summary()
    s["wall_s"] = round(time.time() - t0, 1)
    tw.export(ROOT / "data" / "telemetry" / f"e4_{arm or 'none'}_{policy}")
    if agent is not None:
        h = agent.history
        s["assessments"] = len(h)
        s["assessments_exact"] = sum(1 for x in h if set(x["pred"]) == set(x["truth"]))
    tele = tw.tele_net
    return s, tele


def e4(hours=6.0, arms=("none", "A0", "A3", "A4", "A5", "A6", "A7"), policies=("window", "rl")):
    data = [d for d in json.load(open(ROOT / "data" / "dataset.json", encoding="utf-8")) if d["split"] == "test"]
    replay = load_replay()
    # A7 replay records: same LLM outcome as A5 with SMT fixes, derived like analyze.derive_a7
    from ..eval.analyze import _load, derive_a7, _dataset
    a7 = derive_a7(_load("e1_runs.jsonl"), _dataset())
    for r in a7:
        replay.setdefault(("A7", r["config_id"]), []).append(
            {"pred": r["predicted_violations"], "fixes": r["fixes"], "seconds": r["seconds"], "escalated": r.get("escalated")})
    out = {"hours": hours, "arms": {}, "policies": {}, "series": {}}
    for arm in arms:
        s, tele = run_closed_loop(None if arm == "none" else arm, "immediate" if arm != "none" else "none", hours, data, replay)
        out["arms"][arm] = s
        out["series"][arm] = [{k: r[k] for k in ("t", "unciphered", "spoofable", "noncompliant_sites", "attack_success")}
                              for r in tele[::6]]
        print(arm, {k: s[k] for k in ("unciphered_active_ue_hours", "spoofable_ue_hours", "attack_success", "mttr_s",
                                       "pushes", "unnecessary_pushes", "remediation_outage_ue_hours", "wall_s")}, flush=True)
        (RES / "e4_twin.json").write_text(json.dumps(out, indent=1, default=float))
    for pol in policies:
        s, _ = run_closed_loop("A5", pol, hours, data, replay)
        out["policies"][pol] = s
        print("A5 /", pol, {k: s[k] for k in ("unciphered_active_ue_hours", "spoofable_ue_hours", "attack_success",
                                              "remediation_outage_ue_hours")}, flush=True)
        (RES / "e4_twin.json").write_text(json.dumps(out, indent=1, default=float))
    out["policies"]["immediate"] = out["arms"].get("A5")
    out["note"] = ("Same seed for every arm: identical mobility, traffic, drift and attack sequence. "
                   "Agent outcome and latency per configuration replayed from E1 measurements; "
                   "configurations without a measured run are left to the 24 h manual audit.")
    (RES / "e4_twin.json").write_text(json.dumps(out, indent=1, default=float))
    return out


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "e5"
    if which == "e5":
        e5()
    elif which == "e4":
        e4(float(sys.argv[2]) if len(sys.argv) > 2 else 6.0)
