"""FastAPI backend for the NOC dashboard.

Run:  python -m uvicorn sectwin.api.server:app --port 8600
The built UI (ui/dist) is served at / when present.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..agents.llm import available_models
from ..agents.pipeline import ARM_LABEL, ARMS, Pipeline, security_excerpt
from ..conf.patch import unified_diff, apply_fixes
from ..conf.security import PROFILES, Profile, SECURITY_PARAMS, evaluate_text, security_view, summarize
from ..kb.clauses import CLAUSES, manifest
from ..repair.smt import optimal_repair
from ..twin.engine import ScenarioConfig, Twin
from ..twin.smo import ComplianceService, ImmediatePolicy, NoRemediation, WindowPolicy, load_replay
from .audit import AuditLog

ROOT = Path(__file__).resolve().parents[2]
DATA = json.load(open(ROOT / "data" / "dataset.json", encoding="utf-8"))
BY_ID = {d["id"]: d for d in DATA}
AUDIT = AuditLog(ROOT / "runs" / "audit_chain.jsonl")

app = FastAPI(title="O-RAN SecTwin")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_pipe: Pipeline | None = None
_pipe_lock = threading.Lock()


def pipeline() -> Pipeline:
    global _pipe
    with _pipe_lock:
        if _pipe is None:
            from ..retrieval.index import ClauseIndex
            _pipe = Pipeline(ClauseIndex(), manifest=manifest())
        return _pipe


# ============================================================ dataset / kb
@app.get("/api/meta")
def meta():
    return {"arms": [{"id": a, "label": ARM_LABEL[a]} for a in ARMS], "params": SECURITY_PARAMS,
            "profiles": [asdict(p) | {"key": p.key(), "describe": p.describe()} for p in PROFILES],
            "models": available_models()}


@app.get("/api/dataset")
def dataset():
    return [{k: d[k] for k in ("id", "category", "split", "vendor", "profile", "mutations", "summary", "note")}
            | {"name": d["identity"]["name"]} for d in DATA]


@app.get("/api/dataset/{cid}")
def dataset_item(cid: str):
    d = BY_ID.get(cid)
    if not d:
        raise HTTPException(404)
    rep = optimal_repair(d["text"], Profile(**d["profile"]))
    patched, _ = apply_fixes(d["text"], rep["fixes"])
    sec = security_view(d["text"])
    return {**d, "optimal_repair": rep, "optimal_diff": unified_diff(d["text"], patched),
            "lines": sec.lines}


@app.get("/api/kb")
def kb():
    return {"clauses": [c.to_dict() for c in CLAUSES], "manifest": manifest()}


# ============================================================ live assessments
JOBS: dict[str, dict] = {}


class AssessReq(BaseModel):
    config_id: str
    arm: str = "A5"
    profile: dict | None = None


@app.post("/api/assess")
def assess(req: AssessReq):
    d = BY_ID.get(req.config_id)
    if not d:
        raise HTTPException(404)
    prof = Profile(**(req.profile or d["profile"]))
    jid = uuid.uuid4().hex[:10]
    job = {"id": jid, "status": "running", "events": [], "result": None, "config_id": req.config_id,
           "arm": req.arm, "profile": asdict(prof), "started": time.time()}
    JOBS[jid] = job

    def work():
        try:
            r = pipeline().run(req.arm, req.config_id, d["text"], prof, on_event=job["events"].append)
            res = r.to_dict()
            truth = summarize(evaluate_text(d["text"], prof))
            res["truth"] = truth["violations"]
            entry = AUDIT.append("assessment", {"config_id": req.config_id, "arm": req.arm, "profile": asdict(prof),
                                                "predicted": r.predicted_violations, "fixes": r.fixes,
                                                "escalated": r.escalated, "model": r.model,
                                                "config_sha256": __import__("hashlib").sha256(d["text"].encode()).hexdigest(),
                                                "retrieved": r.retrieved, "seconds": round(r.seconds, 1)})
            res["audit"] = {"entry_hash": entry["entry_hash"], "prev_hash": entry["prev_hash"]}
            job["result"] = res
            job["status"] = "done"
        except Exception as e:
            job["status"] = "error"
            job["error"] = f"{type(e).__name__}: {e}"

    threading.Thread(target=work, daemon=True).start()
    return {"job": jid}


@app.get("/api/assess/{jid}")
def assess_status(jid: str):
    j = JOBS.get(jid)
    if not j:
        raise HTTPException(404)
    return j


@app.get("/api/runs/{config_id}")
def recorded_runs(config_id: str):
    """Recorded experiment runs for one config (all arms) - lets the console show stored traces."""
    out = []
    for p in sorted((ROOT / "results").glob("e1_runs*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip() and f'"config_id": "{config_id}"' in line:
                out.append(json.loads(line))
    return out


# ============================================================ results
@app.get("/api/results")
def results():
    p = ROOT / "results" / "summary.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text())


@app.post("/api/results/refresh")
def results_refresh():
    from ..eval.analyze import main
    return main()


@app.get("/api/progress")
def progress():
    shards = []
    for p in sorted((ROOT / "runs").glob("progress*.json")):
        try:
            shards.append(json.loads(p.read_text()))
        except Exception:
            pass
    if not shards:
        return {}
    phase = shards[0].get("phase")
    return {"phase": phase, "phase_done": sum(s.get("phase_done", 0) for s in shards if s.get("phase") == phase),
            "phase_total": sum(s.get("phase_total", 0) for s in shards if s.get("phase") == phase),
            "last": shards[0].get("last"), "shards": shards}


@app.get("/api/audit")
def audit(limit: int = 300):
    return {"entries": AUDIT.entries(limit), "verify": AUDIT.verify()}


# ============================================================ twin
class TwinRunner:
    def __init__(self):
        self.twin: Twin | None = None
        self.thread: threading.Thread | None = None
        self.running = False
        self.paused = False
        self.speed = 10.0          # simulated seconds per wall second
        self.lock = threading.Lock()
        self.snapshot = None
        self.scenario = None

    def start(self, scen: dict, mode: str):
        self.stop()
        cfg = ScenarioConfig(**scen)
        live = mode == "live"
        agent = ComplianceService(cfg.arm, mode="live" if live else "replay",
                                  replay=None if live else load_replay(),
                                  pipeline=pipeline(), approval_delay_s=cfg.approval_delay_s)
        pol = {"immediate": ImmediatePolicy(), "window": WindowPolicy(*cfg.window_hours),
               "none": NoRemediation()}.get(cfg.remediation_policy)
        if cfg.remediation_policy == "rl":
            from ..rl.policy import RLPolicy
            pol = RLPolicy.load()
        self.twin = Twin(cfg, DATA, agent=agent, policy=pol)
        self.scenario = scen | {"mode": mode}
        self.running, self.paused = True, False
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        tw = self.twin
        last_snap = 0.0
        while self.running and tw is self.twin:
            if self.paused:
                time.sleep(0.1)
                continue
            t0 = time.time()
            steps = max(1, int(self.speed * 0.1 / tw.cfg.dt))
            with self.lock:
                for _ in range(steps):
                    tw.step()
                    if tw.agent is not None and tw.agent._live_thread is not None:
                        break   # keep sim time aligned with a running live assessment
                if time.time() - last_snap > 0.25:
                    self.snapshot = tw.snapshot()
                    self.snapshot["events"] = list(tw.events)[-60:]
                    self.snapshot["agent"] = {"arm": tw.agent.arm, "mode": tw.agent.mode,
                                              "queue": [q["site"] for q in tw.agent.queue],
                                              "current": None if tw.agent.current is None else
                                              {k: tw.agent.current.get(k) for k in ("site", "item", "t_start")},
                                              "history": tw.agent.history[-20:]} if tw.agent else None
                    self.snapshot["pending"] = [{k: p[k] for k in ("site", "fixes", "ready_t", "source")}
                                                for p in tw.pending_pushes]
                    self.snapshot["running"] = True
                    self.snapshot["speed"] = self.speed
                    self.snapshot["scenario"] = self.scenario
                    last_snap = time.time()
            dt = time.time() - t0
            time.sleep(max(0.0, 0.1 - dt))

    def stop(self):
        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=2)
        self.thread = None


RUNNER = TwinRunner()


class TwinStart(BaseModel):
    scenario: dict = {}
    mode: str = "replay"


@app.post("/api/twin/start")
def twin_start(req: TwinStart):
    RUNNER.start(req.scenario, req.mode)
    return {"ok": True}


class TwinCtl(BaseModel):
    action: str
    value: float | None = None
    site: int | None = None
    attacker: dict | None = None


@app.post("/api/twin/control")
def twin_control(req: TwinCtl):
    tw = RUNNER.twin
    if req.action == "pause":
        RUNNER.paused = True
    elif req.action == "resume":
        RUNNER.paused = False
    elif req.action == "speed" and req.value:
        RUNNER.speed = float(req.value)
    elif req.action == "stop":
        RUNNER.stop()
        if RUNNER.snapshot:
            RUNNER.snapshot["running"] = False
    elif tw is not None and req.action == "inject_drift" and req.site is not None:
        with RUNNER.lock:
            tw._inject_config(tw.sites[req.site])
    elif tw is not None and req.action == "inject_malicious" and req.site is not None:
        with RUNNER.lock:
            tw._inject_config(tw.sites[req.site], malicious=True)
    elif tw is not None and req.action == "add_attacker" and req.attacker:
        from ..twin.engine import Attacker
        with RUNNER.lock:
            tw.attackers.append(Attacker(**req.attacker))
    elif tw is not None and req.action == "clear_attackers":
        with RUNNER.lock:
            tw.attackers.clear()
    return {"ok": True}


@app.get("/api/twin/site/{idx}")
def twin_site(idx: int):
    tw = RUNNER.twin
    if tw is None:
        raise HTTPException(404)
    s = tw.sites[idx]
    labels = evaluate_text(s.text, tw.profile)
    return {"idx": idx, "name": s.ident.name, "text": s.text, "item": s.item_id,
            "labels": {k: v.to_dict() for k, v in labels.items()},
            "excerpt": security_excerpt(s.text), "lines": security_view(s.text).lines}


@app.get("/api/twin/telemetry")
def twin_telemetry(last: int = 720):
    tw = RUNNER.twin
    if tw is None:
        return []
    return tw.tele_net[-last:]


@app.post("/api/twin/export")
def twin_export():
    tw = RUNNER.twin
    if tw is None:
        raise HTTPException(404, "no twin running")
    out = ROOT / "data" / "telemetry" / time.strftime("live_%Y%m%d_%H%M%S")
    with RUNNER.lock:
        meta = tw.export(out)
    return {"dir": str(out), "files": meta["files"]}


@app.websocket("/ws/twin")
async def ws_twin(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            snap = RUNNER.snapshot
            if snap is not None:
                await ws.send_text(json.dumps(snap, default=float))
            await asyncio.sleep(0.25)
    except (WebSocketDisconnect, RuntimeError):
        return


# ============================================================ static UI
DIST = ROOT / "ui" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = DIST / path
        if path and f.exists() and f.is_file():
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
