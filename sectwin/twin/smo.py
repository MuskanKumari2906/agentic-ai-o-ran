"""SMO compliance service inside the twin, and remediation policies.

ComplianceService
  * receives O1 change notifications (or polls) for every site whose config hash differs
    from the last approved one,
  * runs one assessment at a time (one GPU), so assessments queue up,
  * ``replay`` mode: uses the MEASURED outcome and latency of the chosen arm on that exact
    dataset config from the E1 experiment log (results/e1_runs.jsonl),
  * ``live`` mode: calls the real pipeline in a background thread (used by the dashboard).
  * findings -> human approval delay -> remediation policy decides when to push the fix.
"""
from __future__ import annotations

import json
import threading
from collections import deque
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def load_replay(path: Path | None = None) -> dict:
    """(arm, config_id) -> list of measured run records (several repeats)."""
    paths = [path] if path else sorted((ROOT / "results").glob("e1_runs*.jsonl"))
    table: dict = {}
    lines = []
    for p in paths:
        if p.exists():
            lines += p.read_text(encoding="utf-8").splitlines()
    for line in lines:
        if not line.strip():
            continue
        r = json.loads(line)
        table.setdefault((r["arm"], r["config_id"]), []).append(
            {"pred": r["predicted_violations"], "fixes": r["fixes"], "seconds": r["seconds"],
             "escalated": r.get("escalated", False)})
    return table


class ComplianceService:
    def __init__(self, arm: str, mode: str = "replay", replay: dict | None = None, pipeline=None,
                 approval_delay_s: float = 120.0, auto_approve_confirmed: bool = False):
        self.arm = arm
        self.mode = mode
        self.replay = replay if replay is not None else load_replay()
        self.pipeline = pipeline
        self.approval_delay_s = approval_delay_s
        self.auto_approve = auto_approve_confirmed
        self.queue: deque = deque()
        self.busy_until = -1.0
        self.current: dict | None = None
        self.history: list[dict] = []
        self._live_result = None
        self._live_thread = None
        self.rng = np.random.default_rng(11)

    # -------------------------------------------------------------- inputs
    def notify_change(self, twin, site):
        if hash(site.text) == site.approved_hash:
            return
        if any(q["site"] == site.idx for q in self.queue):
            self.queue = deque(q for q in self.queue if q["site"] != site.idx)
        self.queue.append({"site": site.idx, "item": site.item_id, "text": site.text, "t_change": twin.t,
                           "drift_t": site.drift_t})

    def poll(self, twin):
        for s in twin.sites:
            self.notify_change(twin, s)

    # -------------------------------------------------------------- per tick
    def tick(self, twin):
        if twin.cfg.detection == "poll" and int(twin.t) % int(twin.cfg.poll_interval_s) == 0:
            self.poll(twin)
        if self.current is not None:
            if self._live_thread is not None:
                if not self._live_thread.is_alive():
                    self._finish(twin, self._live_result)
            elif twin.t >= self.busy_until:
                self._finish(twin, self.current["result"])
        if self.current is None and self.queue:
            job = self.queue.popleft()
            site = twin.sites[job["site"]]
            if site.text != job["text"]:
                return  # superseded
            self._start(twin, job)

    def _start(self, twin, job):
        recs = self.replay.get((self.arm, job["item"])) if (self.mode == "replay" and job["item"]) else None
        if self.mode == "live" or (not recs and self.pipeline is not None):
            self.current = {**job, "t_start": twin.t}
            prof = twin.profile

            def work():
                r = self.pipeline.run(self.arm, job["item"] or f"site-{job['site']}", job["text"], prof)
                self._live_result = {"pred": r.predicted_violations, "fixes": r.fixes, "seconds": r.seconds,
                                     "escalated": r.escalated, "run": r.to_dict()}
            self._live_result = None
            self._live_thread = threading.Thread(target=work, daemon=True)
            self._live_thread.start()
            twin.log("assessment_started", job["site"], arm=self.arm, mode="live")
            return
        if not recs:
            # config not in the measured set (e.g. after a partial fix): treated as not assessable,
            # escalated to the periodic human audit
            twin.log("assessment_skipped", job["site"], reason="no measured result for this config")
            return
        rec = recs[int(self.rng.integers(len(recs)))]
        self.current = {**job, "t_start": twin.t, "result": rec}
        self.busy_until = twin.t + rec["seconds"]
        twin.log("assessment_started", job["site"], arm=self.arm, mode="replay", expected_s=round(rec["seconds"], 1))

    def _finish(self, twin, res):
        job = self.current
        self.current = None
        self._live_thread = None
        if res is None:
            return
        site = twin.sites[job["site"]]
        pred = res["pred"]
        h = {"site": job["site"], "item": job["item"], "t_change": job["t_change"], "t_done": twin.t,
             "pred": pred, "fixes": res["fixes"], "truth": list(site.violations), "escalated": res.get("escalated")}
        self.history.append(h)
        twin.log("assessment_done", job["site"], arm=self.arm, predicted=pred, truth=site.violations,
                 seconds=round(twin.t - job["t_start"], 1), run=res.get("run"))
        if site.text != job["text"]:
            return
        if pred and site.drift_t is not None:
            twin.acc["detections"] += 1
            twin.acc["ttd"].append(twin.t - site.drift_t)
            site.detected_t = twin.t
        if not pred:
            site.approved_hash = hash(site.text)
            return
        fixes = res["fixes"] or {}
        if not fixes:
            twin.log("escalated_to_human", job["site"], reason="violation without a valid fix")
            return
        delay = 0.0 if self.auto_approve else self.approval_delay_s * float(self.rng.uniform(0.5, 1.5))
        twin.schedule_push(job["site"], fixes, twin.t + delay, f"smo:{self.arm}", h)


# ====================================================================== policies
class ImmediatePolicy:
    name = "immediate"

    def allow(self, twin, push) -> bool:
        return True


class WindowPolicy:
    """Push only inside the maintenance window (default 02:00-04:00), except critical issues."""
    name = "window"

    def __init__(self, start=2.0, end=4.0, critical_params=("o1_transport",)):
        self.start, self.end = start, end
        self.critical = set(critical_params)

    def allow(self, twin, push) -> bool:
        if any(p in self.critical for p in push["fixes"]):
            return True
        h = twin.hour
        return self.start <= h < self.end


class NoRemediation:
    name = "none"

    def allow(self, twin, push) -> bool:
        return False
