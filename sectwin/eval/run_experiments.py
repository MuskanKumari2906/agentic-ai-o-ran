"""Overnight experiment runner (resumable).

Phases (in this order, so the most important results exist first):
  e1:r0   arms A0-A7 on the test split, repeat 0
  e2      metamorphic variants (12 configs x 4 variants) for A0, A3, A5
  e3      poisoned knowledge base (12 configs) for A3, A4, A5
  e1:r1   arms A1-A6 + A7 on the test split, repeat 1
  e1x     A5x (cross-family critic) on the test split, repeat 0

Every finished run is appended to results/<exp>_runs.jsonl. On restart, finished
(exp, arm, config, variant, rep) keys are skipped; every LLM call is also cached on disk.
"""
from __future__ import annotations

import argparse
import json
import time
import traceback
from pathlib import Path

from ..agents.llm import available_models
from ..agents.pipeline import Pipeline
from ..conf.security import Profile, evaluate_text, summarize
from ..kb.clauses import manifest
from ..retrieval.index import ClauseIndex
from .metrics import score
from .variants import POISON, poisoned_corpus, variants

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "results"
PROGRESS = ROOT / "runs" / "progress.json"


def _progress_path():
    k, n = SHARD
    return PROGRESS if k == 0 else ROOT / "runs" / f"progress_{k}.json"


SHARD = (0, 1)


def _out_path(base: str) -> Path:
    k, n = SHARD
    stem = base.replace(".jsonl", "")
    return RES / (f"{stem}.s{k}.jsonl" if n > 1 else base)


def _done_keys(base: str) -> set:
    keys = set()
    stem = base.replace(".jsonl", "")
    for path in list(RES.glob(f"{stem}.jsonl")) + list(RES.glob(f"{stem}.s*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                keys.add((r["arm"], r["config_id"], r.get("variant", ""), r.get("rep", 0)))
    return keys


def _progress(**kw):
    P = _progress_path()
    P.parent.mkdir(parents=True, exist_ok=True)
    cur = {}
    if P.exists():
        try:
            cur = json.loads(P.read_text())
        except Exception:
            cur = {}
    cur.update(kw)
    cur["shard"] = f"{SHARD[0]}/{SHARD[1]}"
    cur["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    P.write_text(json.dumps(cur, indent=1))


def run_phase(name, out_file, jobs, pipe_for):
    """jobs: list of dicts {arm, item, text, variant, rep}"""
    path = _out_path(out_file)
    done = _done_keys(out_file)
    k, n = SHARD
    jobs = [j for j in jobs if int(j["item"]["id"].split("-")[1]) % n == k]
    todo = [j for j in jobs if (j["arm"], j["item"]["id"], j.get("variant", ""), j.get("rep", 0)) not in done]
    _progress(phase=name, phase_total=len(jobs), phase_done=len(jobs) - len(todo))
    print(f"[{name}] {len(jobs) - len(todo)}/{len(jobs)} already done", flush=True)
    t0 = time.time()
    for k, j in enumerate(todo):
        it = j["item"]
        prof = Profile(**it["profile"])
        text = j.get("text") or it["text"]
        try:
            pipe = pipe_for(j)
            r = pipe.run(j["arm"], it["id"], text, prof).to_dict()
        except Exception as e:
            traceback.print_exc()
            r = {"arm": j["arm"], "config_id": it["id"], "error": f"{type(e).__name__}: {e}",
                 "predicted_violations": [], "confirmed_findings": [], "fixes": {}, "rounds": [],
                 "seconds": 0.0, "tokens": 0}
        item_for_score = dict(it)
        if text != it["text"]:
            item_for_score = dict(it, text=text)
        r["score"] = score(r, item_for_score)
        r["truth"] = it["summary"]["violations"]
        r["category"] = it["category"]
        r["variant"] = j.get("variant", "")
        r["rep"] = j.get("rep", 0)
        r["exp"] = name
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(r) + "\n")
        el = time.time() - t0
        _progress(phase=name, phase_total=len(jobs), phase_done=len(jobs) - len(todo) + k + 1,
                  last=f"{j['arm']} {it['id']} {j.get('variant', '')} r{j.get('rep', 0)}: "
                       f"pred={r['predicted_violations']} truth={r['truth']} {r['seconds']:.0f}s",
                  eta_min=round(el / (k + 1) * (len(todo) - k - 1) / 60, 1))
        print(f"[{name}] {k + 1}/{len(todo)} {j['arm']} {it['id']} {j.get('variant', '')} "
              f"pred={r['predicted_violations']} truth={r['truth']} {r['seconds']:.0f}s", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phases", default="e1:r0,e2,e3,e1:r1,e1x")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--shard", default="0/1")
    args = ap.parse_args()
    global SHARD
    SHARD = tuple(int(x) for x in args.shard.split("/"))
    RES.mkdir(exist_ok=True)
    data = json.load(open(ROOT / "data" / "dataset.json", encoding="utf-8"))
    test = [d for d in data if d["split"] == "test"]
    if args.limit:
        test = test[:args.limit]
    while not available_models():
        print("waiting for Ollama ...", flush=True)
        time.sleep(30)

    clean_index = ClauseIndex()
    pipes = {}

    def pipe_for(j):
        key = ("poison" if j.get("poison") else "clean", j.get("rep", 0))
        if key not in pipes:
            idx = poison_index() if j.get("poison") else clean_index
            pipes[key] = Pipeline(idx, manifest=manifest(), seed=j.get("rep", 0))
        return pipes[key]

    _pidx = {}

    def poison_index():
        if "i" not in _pidx:
            _pidx["i"] = ClauseIndex(poisoned_corpus())
        return _pidx["i"]

    for ph in args.phases.split(","):
        if ph.startswith("e1:r"):
            rep = int(ph.split("r")[1])
            arms = ["A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7"] if rep == 0 else \
                ["A1", "A2", "A3", "A4", "A5", "A6", "A7"]
            jobs = [{"arm": a, "item": it, "rep": rep} for it in test for a in arms]
            run_phase(ph, "e1_runs.jsonl", jobs, pipe_for)
        elif ph == "e1x":
            jobs = [{"arm": "A5x", "item": it, "rep": 0} for it in test]
            run_phase(ph, "e1_runs.jsonl", jobs, pipe_for)
        elif ph == "e2":
            sel = [it for it in test if it["category"] in ("single", "multi", "decoy", "vendor_default")][:12]
            jobs = []
            for it in sel:
                for vname, vtext in variants(it).items():
                    for a in ("A0", "A3", "A5"):
                        jobs.append({"arm": a, "item": it, "text": vtext, "variant": vname})
            run_phase(ph, "e2_runs.jsonl", jobs, pipe_for)
        elif ph == "e3":
            rel = {"integrity_algorithms", "ciphering_algorithms", "drb_ciphering", "o1_transport",
                   "f1c_protection", "tls_min_version"}
            sel = [it for it in test if rel & set(it["mutations_params"] if "mutations_params" in it else
                                                   [m for m in it["settings"]])][:0]
            # configs whose truth involves a poisoned topic, plus clean ones the poison could flip
            sel = [it for it in test if set(it["summary"]["violations"]) & rel][:8] + \
                  [it for it in test if it["category"] in ("clean", "decoy")][:4]
            jobs = [{"arm": a, "item": it, "poison": True, "variant": "poisoned"} for it in sel
                    for a in ("A3", "A4", "A5")]
            run_phase(ph, "e3_runs.jsonl", jobs, pipe_for)
    _progress(phase="finished")
    print("all phases finished", flush=True)


if __name__ == "__main__":
    main()
