"""Scoring of one arm run against the oracle labels."""
from __future__ import annotations

from rapidfuzz import fuzz

from ..conf.patch import apply_fixes
from ..conf.security import CIPHER_ALGS, INTEG_ALGS, Profile, SECURITY_PARAMS, evaluate_text, security_view, summarize
from ..kb.clauses import BY_ID
from ..twin.engine import CAP_CLASSES


def ue_compatible(text: str) -> bool:
    """Can every UE capability class obtain non-null integrity and some ciphering with this config?"""
    sec = security_view(text)
    ca = [CIPHER_ALGS.index(a) for a in (sec.get("ciphering_algorithms") or []) if a in CIPHER_ALGS]
    ia = [INTEG_ALGS.index(a) for a in (sec.get("integrity_algorithms") or []) if a in INTEG_ALGS]
    for cs, is_ in CAP_CLASSES:
        c = next((a for a in ca if a in cs), None)
        i = next((a for a in ia if a in is_), None)
        if c is None or i is None or i == 0:
            return False
    return True


def score(run: dict, item: dict) -> dict:
    prof = Profile(**item["profile"])
    truth = set(item["summary"]["violations"])
    pred = set(run["predicted_violations"])
    tp, fp, fn = len(pred & truth), len(pred - truth), len(truth - pred)
    tn = len(SECURITY_PARAMS) - tp - fp - fn
    labels = item["labels"]

    # citation correctness per confirmed finding
    cites = []
    for f in run.get("confirmed_findings", []):
        p = f.get("parameter")
        cl = BY_ID.get(f.get("clause_id", ""))
        exists = cl is not None
        quote_ok = exists and fuzz.partial_ratio((f.get("quote") or "").lower(), cl.text.lower()) >= 90
        supports = False
        if p in labels and labels[p]["verdict"] == "violation":
            gov = set()
            for r in labels[p]["reasons"]:
                gov |= set(r["clause_ids"])
            supports = f.get("clause_id") in gov
        cites.append(exists and quote_ok and supports)

    # fix correctness
    fixes = run.get("fixes") or {}
    if fixes:
        patched, errs = apply_fixes(item["text"], fixes)
        after = summarize(evaluate_text(patched, prof))
        resolved = not (set(after["violations"]) & truth)
        new = set(after["violations"]) - truth
        compat = ue_compatible(patched)
        fix_ok = (not errs) and resolved and not new and compat and after["compliant"]
    else:
        resolved = not truth
        new = set()
        compat = True
        fix_ok = not truth

    # reflection flips (round 0 vs final), per parameter
    flips = {"wrong_to_right": 0, "right_to_wrong": 0}
    rounds = run.get("rounds") or []
    if len(rounds) > 1 and rounds[0].get("assessment"):
        r0 = {f.get("parameter") for f in (rounds[0]["assessment"].get("findings") or [])
              if isinstance(f, dict) and f.get("verdict") == "violation"}
        for p in SECURITY_PARAMS:
            before_ok = (p in r0) == (p in truth)
            after_ok = (p in pred) == (p in truth)
            if not before_ok and after_ok:
                flips["wrong_to_right"] += 1
            if before_ok and not after_ok:
                flips["right_to_wrong"] += 1

    return {
        "config_correct": (len(pred) > 0) == (len(truth) > 0),
        "exact_set": pred == truth,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "n_cites": len(cites), "cites_correct": sum(cites),
        "fix_correct": fix_ok, "fix_resolved": resolved, "fix_new_violations": sorted(new), "fix_ue_compatible": compat,
        "unnecessary_fix": bool(fixes) and not truth,
        "has_truth": bool(truth),
        **flips,
    }


def aggregate(rows: list[dict]) -> dict:
    import numpy as np
    n = len(rows)
    if n == 0:
        return {}
    tp = sum(r["tp"] for r in rows)
    fp = sum(r["fp"] for r in rows)
    fn = sum(r["fn"] for r in rows)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    nc = sum(r["n_cites"] for r in rows)
    return {
        "n": n,
        "config_accuracy": float(np.mean([r["config_correct"] for r in rows])),
        "exact_match": float(np.mean([r["exact_set"] for r in rows])),
        "precision": prec, "recall": rec, "f1": f1,
        "citation_correct": (sum(r["cites_correct"] for r in rows) / nc) if nc else None,
        # fix correctness is measured on non-compliant configs; unnecessary changes on compliant ones
        "fix_correct": float(np.mean([r["fix_correct"] for r in rows if r.get("has_truth", True)]))
        if any(r.get("has_truth", True) for r in rows) else None,
        "unnecessary_change_rate": float(np.mean([r["unnecessary_fix"] for r in rows if not r.get("has_truth", True)]))
        if any(not r.get("has_truth", True) for r in rows) else None,
        "wrong_to_right": sum(r["wrong_to_right"] for r in rows),
        "right_to_wrong": sum(r["right_to_wrong"] for r in rows),
    }
