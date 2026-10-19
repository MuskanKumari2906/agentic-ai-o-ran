"""Aggregate experiment logs into results/summary.json (tables used by the dashboard and the report).

Statistics: 95% bootstrap confidence intervals over configurations (2000 resamples);
paired exact McNemar tests on per-configuration correctness.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

from ..conf.security import Profile
from ..repair.smt import repair_from_findings
from .metrics import aggregate, score
from .variants import POISON

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "results"
ARM_ORDER = ["A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A5x"]


def _load(name):
    stem = name.replace(".jsonl", "")
    out = []
    for p in sorted(list(RES.glob(f"{stem}.jsonl")) + list(RES.glob(f"{stem}.s*.jsonl"))):
        out += [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    return out


def _dataset():
    return {d["id"]: d for d in json.load(open(ROOT / "data" / "dataset.json", encoding="utf-8"))}


def boot_ci(rows_by_cfg: dict, stat, n_boot=2000, seed=0):
    keys = list(rows_by_cfg)
    if not keys:
        return None
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_boot):
        pick = rng.integers(len(keys), size=len(keys))
        rows = [r for i in pick for r in rows_by_cfg[keys[i]]]
        v = stat(rows)
        if v is not None:
            vals.append(v)
    if not vals:
        return None
    return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))]


def mcnemar(a: dict, b: dict):
    """Exact McNemar on per-config correctness (majority over repeats)."""
    common = set(a) & set(b)
    n01 = sum(1 for k in common if a[k] and not b[k])
    n10 = sum(1 for k in common if not a[k] and b[k])
    n = n01 + n10
    if n == 0:
        return {"a_only": 0, "b_only": 0, "p": 1.0}
    k = min(n01, n10)
    p = min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)
    return {"a_only": n01, "b_only": n10, "p": round(p, 4)}


def derive_a7(runs, data):
    """A7 computed post hoc from A5 runs: same LLM calls, fixes from the SMT repair engine."""
    out = []
    for r in runs:
        if r["arm"] != "A5":
            continue
        it = data[r["config_id"]]
        r7 = dict(r, arm="A7")
        if r["confirmed_findings"]:
            rep = repair_from_findings(it["text"], r["confirmed_findings"],
                                       emergency=Profile(**it["profile"]).emergency_unauth_supported)
            r7["fixes"] = rep["fixes"] if rep else {}
        r7["score"] = score(r7, it)
        out.append(r7)
    return out


def rescore(runs, data, text_key=None):
    for r in runs:
        it = data.get(r["config_id"])
        if it is not None and not r.get("variant"):
            r["score"] = score(r, it)
    return runs


def e1_tables(runs, data):
    runs = rescore([r for r in runs if r["arm"] != "A7"], data)
    runs = runs + derive_a7(runs, data)
    by_arm = defaultdict(list)
    for r in runs:
        by_arm[r["arm"]].append(r)
    table, cats, perf = {}, {}, {}
    correct_by_arm = {}
    for arm in ARM_ORDER:
        rs = by_arm.get(arm)
        if not rs:
            continue
        rows = [r["score"] for r in rs]
        agg = aggregate(rows)
        by_cfg = defaultdict(list)
        for r in rs:
            by_cfg[r["config_id"]].append(r["score"])
        agg["f1_ci"] = boot_ci(by_cfg, lambda x: aggregate(x)["f1"])
        agg["config_accuracy_ci"] = boot_ci(by_cfg, lambda x: aggregate(x)["config_accuracy"])
        agg["fix_correct_ci"] = boot_ci({k: v for k, v in by_cfg.items() if v[0].get("has_truth")},
                                        lambda x: aggregate(x)["fix_correct"])
        agg["seconds_mean"] = float(np.mean([r["seconds"] for r in rs]))
        agg["tokens_mean"] = float(np.mean([r.get("tokens", 0) for r in rs]))
        agg["escalation_rate"] = float(np.mean([bool(r.get("escalated")) for r in rs]))
        agg["rounds_mean"] = float(np.mean([max(1, len(r.get("rounds") or [])) for r in rs]))
        agg["repeats"] = len({r.get("rep", 0) for r in rs})
        agg["configs"] = len(by_cfg)
        table[arm] = agg
        c = defaultdict(list)
        for r in rs:
            c[r.get("category", "?")].append(r["score"]["exact_set"])
        cats[arm] = {k: float(np.mean(v)) for k, v in c.items()}
        correct_by_arm[arm] = {k: (np.mean([s["exact_set"] for s in v]) >= 0.5) for k, v in by_cfg.items()}
        perf[arm] = {"tp": sum(s["tp"] for s in rows), "fp": sum(s["fp"] for s in rows), "fn": sum(s["fn"] for s in rows)}
    pairs = [("A3", "A1"), ("A3", "A2"), ("A4", "A3"), ("A5", "A3"), ("A5", "A4"), ("A6", "A3"), ("A5", "A6"),
             ("A0", "A3"), ("A0", "A5"), ("A5x", "A5")]
    tests = {f"{a} vs {b}": mcnemar(correct_by_arm[a], correct_by_arm[b]) for a, b in pairs
             if a in correct_by_arm and b in correct_by_arm}
    return {"arms": table, "by_category": cats, "counts": perf, "mcnemar_exact_set": tests}


def e2_tables(e2, e1, data):
    base = {}
    for r in e1:
        if r.get("rep", 0) == 0:
            base[(r["arm"], r["config_id"])] = set(r["predicted_violations"])
    out = defaultdict(lambda: defaultdict(lambda: {"n": 0, "consistent": 0, "correct": 0}))
    for r in e2:
        b = base.get((r["arm"], r["config_id"]))
        cell = out[r["arm"]][r["variant"]]
        cell["n"] += 1
        cell["correct"] += int(r["score"]["exact_set"])
        if b is not None:
            cell["consistent"] += int(set(r["predicted_violations"]) == b)
    return {a: {v: {**c, "consistency": c["consistent"] / c["n"] if c["n"] else None,
                    "accuracy": c["correct"] / c["n"] if c["n"] else None} for v, c in vs.items()}
            for a, vs in out.items()}


def e3_tables(e3, e1):
    poison_ids = {p.clause_id for p in POISON}
    base = {(r["arm"], r["config_id"]): r for r in e1 if r.get("rep", 0) == 0}
    out = {}
    for arm in ("A3", "A4", "A5"):
        rs = [r for r in e3 if r["arm"] == arm]
        if not rs:
            continue
        cited = sum(1 for r in rs for f in r["confirmed_findings"] if f.get("clause_id") in poison_ids)
        retrieved = sum(1 for r in rs if set(r.get("retrieved") or []) & poison_ids)
        flipped, degraded = 0, 0
        for r in rs:
            b = base.get((arm, r["config_id"]))
            if b is None:
                continue
            if set(b["predicted_violations"]) != set(r["predicted_violations"]):
                flipped += 1
            if b["score"]["exact_set"] and not r["score"]["exact_set"]:
                degraded += 1
        out[arm] = {"runs": len(rs), "runs_with_poison_retrieved": retrieved,
                    "confirmed_findings_citing_poison": cited, "verdict_changed_vs_clean": flipped,
                    "correct_to_wrong_vs_clean": degraded,
                    "accuracy_poisoned": float(np.mean([r["score"]["exact_set"] for r in rs]))}
    return out


def main():
    data = _dataset()
    e1 = _load("e1_runs.jsonl")
    e2 = _load("e2_runs.jsonl")
    e3 = _load("e3_runs.jsonl")
    summary = {"e1": e1_tables(e1, data) if e1 else {}, "e2": e2_tables(e2, e1, data) if e2 else {},
               "e3": e3_tables(e3, e1) if e3 else {},
               "counts": {"e1_runs": len(e1), "e2_runs": len(e2), "e3_runs": len(e3)}}
    for name in ("e4_twin.json", "e5_cost.json", "e6_rl.json"):
        p = RES / name
        if p.exists():
            summary[name.split("_")[0]] = json.loads(p.read_text())
    (RES / "summary.json").write_text(json.dumps(summary, indent=1, default=float))
    return summary


if __name__ == "__main__":
    s = main()
    for arm, a in s.get("e1", {}).get("arms", {}).items():
        print(f"{arm:4s} n={a['n']:3d} acc={a['config_accuracy']:.2f} F1={a['f1']:.2f} {a['f1_ci']} "
              f"P={a['precision']:.2f} R={a['recall']:.2f} cite={a["citation_correct"]} fix={a["fix_correct"]} "
              f"t={a['seconds_mean']:.0f}s")
