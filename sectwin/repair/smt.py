"""Clause compiler + SMT minimal repair (z3).

Clause compiler: each clause ID that can govern a configuration value is compiled into a
constraint over the parameter's value. Repair: z3's Optimize finds the assignment that
satisfies every compiled constraint while changing as little as possible (positions changed
in algorithm lists, plus one per changed scalar).

Two uses:
* ``repair_from_findings`` (arm A7): constraints come ONLY from the clauses cited in the
  arm's own confirmed findings. No oracle access.
* ``optimal_repair`` (scoring): constraints come from the oracle's violated rules; the result is
  the reference minimal fix used to score every arm's fix ("fix optimality").
"""
from __future__ import annotations

import z3

from ..conf.security import (ALLOWED_VALUES, CIPHER_ALGS, INTEG_ALGS, Profile, SECURITY_PARAMS, evaluate,
                             security_view)

SLOTS = 4  # algorithm list positions


def _compile(param: str, clause_ids: set[str], emergency: bool):
    """Return a list of constraint builders f(vars) -> z3 expr for this parameter."""
    cons = []
    if param in ("ciphering_algorithms", "integrity_algorithms"):
        null = 0
        if param == "integrity_algorithms" and clause_ids & {"TS33.501-5.3.3", "TS33.501-D.1", "TS33.501-6.7.3"}:
            if emergency:
                cons.append(lambda s: s[0] != null)            # NIA0 must not be top priority
            else:
                cons.append(lambda s: z3.And([x != null for x in s]))  # NIA0 disabled
        if param == "ciphering_algorithms" and "OSB-1" in clause_ids:
            if emergency:
                cons.append(lambda s: s[0] != null)
            else:
                cons.append(lambda s: z3.And([x != null for x in s]))
        if "OSB-3" in clause_ids:
            cons.append(lambda s: z3.Or(s[0] == 2, s[0] == 3))
        # always: at least one non-null algorithm
        cons.append(lambda s: z3.Or([z3.And(x >= 1, x <= 3) for x in s]))
        return cons
    if param == "drb_ciphering" and clause_ids & {"OSB-2"}:
        return [lambda v: v == ALLOWED_VALUES["drb_ciphering"].index("yes")]
    if param in ("f1c_protection", "n2_protection", "n3_protection", "xn_protection", "e2_protection"):
        none_idx = ALLOWED_VALUES[param].index("none")
        return [lambda v, n=none_idx: v != n]
    if param == "o1_transport":
        return [lambda v: v != ALLOWED_VALUES["o1_transport"].index("netconf_plain")]
    if param == "tls_min_version":
        if "OSB-5" in clause_ids:
            return [lambda v: v == 3]
        return [lambda v: v >= 2]
    return []


def _solve(sec, targets: dict[str, set[str]], emergency: bool):
    opt = z3.Optimize()
    cost_terms = []
    pref_terms = []
    decode = {}
    for p, clauses in targets.items():
        cur = sec.get(p)
        if p in ("ciphering_algorithms", "integrity_algorithms"):
            alg = CIPHER_ALGS if p.startswith("ciph") else INTEG_ALGS
            cur_idx = [alg.index(a) if a in alg else -1 for a in (cur or [])][:SLOTS]
            cur_idx += [-1] * (SLOTS - len(cur_idx))
            s = [z3.Int(f"{p}_{i}") for i in range(SLOTS)]
            for i, x in enumerate(s):
                opt.add(x >= -1, x <= 3)
                if i > 0:
                    opt.add(z3.Implies(s[i - 1] == -1, x == -1))      # contiguous list
            for i in range(SLOTS):
                for j in range(i + 1, SLOTS):
                    opt.add(z3.Implies(s[i] != -1, s[i] != s[j]))    # no duplicates
            for c in _compile(p, clauses, emergency):
                opt.add(c(s))
            # cost = algorithms added + algorithms removed + pairs whose relative order flipped
            cur_set = [a for a in cur_idx if a >= 0]
            present = {a: z3.Or([x == a for x in s]) for a in range(4)}
            pos = {a: z3.Sum([z3.If(s[i] == a, i, 0) for i in range(SLOTS)]) for a in range(4)}
            for a in range(4):
                cost_terms.append(z3.If(present[a], 0 if a in cur_set else 1, 1 if a in cur_set else 0))
            for i, a in enumerate(cur_set):
                for b in cur_set[i + 1:]:
                    cost_terms.append(z3.If(z3.And(present[a], present[b], pos[a] > pos[b]), 1, 0))
            # tie-break: do not introduce SNOW-3G (index 1) when AES/ZUC would do
            pref_terms.append(z3.If(z3.And(present[1], 1 not in cur_set), 1, 0))
            decode[p] = ("list", s, alg)
        else:
            vals = ALLOWED_VALUES[p]
            ci = vals.index(str(cur)) if str(cur) in vals else -1
            v = z3.Int(p)
            opt.add(v >= 0, v < len(vals))
            for c in _compile(p, clauses, emergency):
                opt.add(c(v))
            cost_terms.append(z3.If(v != ci, 1, 0))
            decode[p] = ("scalar", v, vals)
    total = z3.Sum(cost_terms) if cost_terms else z3.IntVal(0)
    opt.minimize(total)
    if pref_terms:
        opt.minimize(z3.Sum(pref_terms))
    if opt.check() != z3.sat:
        return None
    m = opt.model()
    fixes = {}
    for p, (kind, var, dom) in decode.items():
        if kind == "list":
            vals = [m.eval(x).as_long() for x in var]
            new = [dom[i] for i in vals if i >= 0]
            if new != [str(a).lower() for a in (sec.get(p) or [])]:
                fixes[p] = new
        else:
            new = dom[m.eval(var).as_long()]
            if new != str(sec.get(p)):
                fixes[p] = new
    return {"fixes": fixes, "cost": m.eval(total).as_long()}


def repair_from_findings(text: str, findings: list[dict], emergency: bool | None = None) -> dict | None:
    sec = security_view(text)
    targets: dict[str, set[str]] = {}
    for f in findings:
        p = f.get("parameter")
        if p in SECURITY_PARAMS:
            targets.setdefault(p, set()).add(f.get("clause_id", ""))
    if emergency is None:
        emergency = any("emergency" in (f.get("reason") or "").lower() and "not" not in (f.get("reason") or "").lower()
                        for f in findings)
    return _solve(sec, targets, emergency) if targets else None


def optimal_repair(text: str, profile: Profile) -> dict:
    sec = security_view(text)
    labels = evaluate(sec, profile)
    targets = {}
    for p, l in labels.items():
        if l.verdict == "violation":
            cl = set()
            for r in l.reasons:
                cl |= set(r.clause_ids)
                cl.add(r.rule_id)
            targets[p] = cl
    if not targets:
        return {"fixes": {}, "cost": 0}
    return _solve(sec, targets, profile.emergency_unauth_supported) or {"fixes": {}, "cost": None}
