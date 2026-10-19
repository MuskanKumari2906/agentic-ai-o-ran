"""Experimental arms A0-A6 (+ A5x cross-family critic, A7 solver repair) as one pipeline.

Arm   RAG  QueryGen  LLM-reflect(text)  Verifier C1-C5  LLM critic
A0    rule-based literal scanner, no LLM
A1    -    -         -                  -               -
A2    yes  -         -                  -               -
A3    yes  yes       -                  -               -
A4    yes  yes       yes                -               -
A5    yes  yes       -                  yes             yes
A6    yes  yes       -                  yes             -
A5x   as A5, critic from a second model family
A7    as A5, but fixes are synthesised by the SMT repair engine from the confirmed findings
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from ..conf.patch import apply_fixes, unified_diff
from ..conf.security import Profile, SECURITY_PARAMS, security_view
from ..kb.clauses import BY_ID, Clause, manifest as trusted_manifest, normative_level
from ..retrieval.index import ClauseIndex
from . import prompts as P
from .llm import CallLog, PRIMARY_MODEL, SECOND_MODEL, chat
from .rules_baseline import assess_a0
from .schema import ASSESSMENT_SCHEMA, CRITIC_SCHEMA, QUERIES_SCHEMA, Assessment
from .verifier import QUOTE_THRESHOLD, _norm, c4_check, verify

ARMS = ["A0", "A1", "A2", "A3", "A4", "A5", "A6", "A5x", "A7"]
ARM_LABEL = {
    "A0": "Rule-based literal scanner", "A1": "LLM only", "A2": "LLM + RAG",
    "A3": "Agentic RAG (single agent)", "A4": "A3 + LLM-only reflection",
    "A5": "A3 + verifier-grounded reflection", "A6": "A3 + verifier only",
    "A5x": "A5 with cross-family critic", "A7": "A5 + SMT minimal repair",
}
MAX_ROUNDS = 3


def numbered(text: str) -> str:
    return "\n".join(f"{i:4d}| {l}" for i, l in enumerate(text.split("\n"), 1))


def security_excerpt(text: str) -> str:
    out = []
    for name in ("security", "interface_security"):
        m = re.search(rf"^{name}\s*=\s*\{{.*?^\}};", text, re.S | re.M)
        if m:
            out.append(m.group(0))
    return "\n\n".join(out)


def clauses_block(clauses: list[Clause]) -> str:
    return "\n\n".join(f"[{c.clause_id}] {c.doc} - {c.title}\n{c.text}" for c in clauses)


def param_table(text: str) -> str:
    sec = security_view(text)
    return "\n".join(f"- {p} (line {sec.lines.get(p)}): {json.dumps(sec.get(p))}" for p in SECURITY_PARAMS)


def assessor_user(text, profile: Profile, clauses: list[Clause] | None) -> str:
    parts = [f"Deployment profile: {profile.describe()}.", "",
             "Security parameters parsed from the file:", param_table(text), "",
             "Configuration file (line numbers on the left):", numbered(text)]
    if clauses:
        parts += ["", "Requirement clauses:", clauses_block(clauses)]
    else:
        parts += ["", P.ASSESSOR_NO_RAG_NOTE]
    return "\n".join(parts)


@dataclass
class RunResult:
    arm: str
    config_id: str
    profile: dict
    model: str
    final: dict | None
    predicted_violations: list[str]
    confirmed_findings: list[dict]
    fixes: dict
    patched: str | None
    diff: str
    escalated: bool
    rounds: list[dict] = field(default_factory=list)
    retrieved: list[str] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)
    seconds: float = 0.0
    tokens: int = 0
    error: str | None = None

    def to_dict(self):
        return self.__dict__.copy()


class Pipeline:
    def __init__(self, index: ClauseIndex | None = None, model: str = PRIMARY_MODEL,
                 critic_model: str = SECOND_MODEL, manifest: dict | None = None, seed: int = 0):
        self.index = index
        self.model = model
        self.critic_model = critic_model
        self.manifest = manifest or trusted_manifest()
        self.seed = seed

    # ---------------------------------------------------------------- building blocks
    def _assess(self, text, profile, clauses, log: CallLog, messages_extra=None):
        msgs = [{"role": "system", "content": P.ASSESSOR_SYSTEM},
                {"role": "user", "content": assessor_user(text, profile, clauses)}]
        if messages_extra:
            msgs += messages_extra
        r = chat(msgs, model=self.model, schema=ASSESSMENT_SCHEMA, seed=self.seed, num_predict=3000)
        log.add("assessor", r)
        self._last_raw = r.content
        return r.data, msgs, r

    def _queries(self, text, profile, log: CallLog) -> list[str]:
        msgs = [{"role": "system", "content": P.QUERYGEN_SYSTEM},
                {"role": "user", "content": f"Deployment profile: {profile.describe()}.\n\n{security_excerpt(text)}"}]
        r = chat(msgs, model=self.model, schema=QUERIES_SCHEMA, seed=self.seed, num_predict=400)
        log.add("query_generator", r)
        q = (r.data or {}).get("queries") or []
        return [str(x) for x in q][:6] or [security_excerpt(text)]

    def _retrieve(self, queries: list[str], k_total=8) -> list[Clause]:
        return [h.clause for h in self.index.multi_search(queries, k_each=4, k_total=k_total)]

    def _revise(self, msgs, prev: dict | None, issues: list[dict], log: CallLog, rnd: int = 1):
        if prev is None:
            raw = (getattr(self, "_last_raw", "") or "")[-1500:]
            prev_txt = ("(your previous output could not be parsed as JSON; it was probably cut off. "
                        "Its end was:)\n" + raw)
        else:
            prev_txt = json.dumps(prev, indent=1)
        extra = [{"role": "assistant", "content": prev_txt if prev is None else json.dumps(prev)},
                 {"role": "user", "content": P.REVISE_USER.format(prev=prev_txt, issues=json.dumps(issues, indent=1))}]
        r = chat(msgs + extra, model=self.model, schema=ASSESSMENT_SCHEMA, seed=self.seed * 100 + rnd,
                 num_predict=3000)
        log.add("assessor_revise", r)
        self._last_raw = r.content
        return r.data

    def _critic(self, system, text, profile, clauses, assessment, verifier_issues, log: CallLog, model):
        sec = security_view(text)
        params = {p: sec.get(p) for p in SECURITY_PARAMS}
        user = (f"Deployment profile: {profile.describe()}.\n\nParsed security parameters:\n{json.dumps(params)}\n\n"
                f"Assessment under review:\n{json.dumps(assessment, indent=1)}\n\n")
        if verifier_issues is not None:
            user += f"Verifier results (C1-C5):\n{json.dumps(verifier_issues, indent=1) if verifier_issues else 'all checks passed'}\n\n"
        user += f"Requirement clauses:\n{clauses_block(clauses)}"
        r = chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                 model=model, schema=CRITIC_SCHEMA, seed=self.seed, num_predict=1200)
        log.add("critic", r)
        return (r.data or {}).get("issues") or []

    def _check_critic_issue(self, iss: dict, retrieved: dict, assessment: dict | None) -> str | None:
        """Critic claims pass the same evidence checks (C3, and C4 for MissedViolation), and must
        target the right kind of parameter: a missed violation must not already be flagged, and a
        scope / verdict / fix complaint must target an existing violation finding."""
        flagged = {f.get("parameter") for f in ((assessment or {}).get("findings") or [])
                   if isinstance(f, dict) and f.get("verdict") == "violation"}
        typ = iss.get("type")
        if typ == "MissedViolation" and iss.get("parameter") in flagged:
            return "parameter is already reported as a violation"
        if typ in ("ScopeError", "WrongVerdict", "BadFix") and iss.get("parameter") not in flagged:
            return "no violation finding on this parameter"
        cid = iss.get("clause_id") or ""
        chunk = retrieved.get(cid)
        if chunk is None or self.manifest.get(cid) != chunk.sha256:
            return "clause not retrieved or failed provenance"
        if fuzz.partial_ratio((iss.get("quote") or "").lower(), chunk.text.lower()) < QUOTE_THRESHOLD:
            return "quote not found"
        if typ == "MissedViolation":
            why = c4_check(iss.get("parameter", ""), iss.get("quote", ""),
                           security_view(self._text).get(iss.get("parameter", "")) if self._text else None)
            if why:
                return why
        if iss.get("parameter") not in SECURITY_PARAMS:
            return "unknown parameter"
        return None

    # ---------------------------------------------------------------- run one arm
    def run(self, arm: str, cfg_id: str, text: str, profile: Profile, on_event=None) -> RunResult:
        t0 = time.time()
        log = CallLog()
        self._text = text

        def emit(kind, **payload):
            if on_event is not None:
                try:
                    on_event({"kind": kind, "t": round(time.time() - t0, 2), **payload})
                except Exception:
                    pass
        emit("start", arm=arm, config_id=cfg_id)
        if arm == "A0":
            out = assess_a0(text)
            fixes = {f["parameter"]: f["fix_value"] for f in out["findings"]}
            patched, _ = apply_fixes(text, fixes)
            return RunResult(arm, cfg_id, profile.__dict__, "none", out,
                             sorted({f["parameter"] for f in out["findings"]}), out["findings"], fixes,
                             patched, unified_diff(text, patched), False, seconds=time.time() - t0)

        clauses: list[Clause] = []
        queries: list[str] = []
        if arm == "A2":
            queries = [security_excerpt(text)]
            clauses = self._retrieve(queries)
        elif arm in ("A3", "A4", "A5", "A6", "A5x", "A7"):
            queries = self._queries(text, profile, log)
            clauses = self._retrieve(queries)
        retrieved = {c.clause_id: c for c in clauses}
        emit("retrieval", queries=queries, clauses=[c.clause_id for c in clauses])

        data, msgs, r = self._assess(text, profile, clauses or None, log)
        rounds = [{"round": 0, "assessment": data, "issues": [], "critic": []}]
        emit("assessment", round=0, assessment=data)
        escalated = False
        final_status: dict = {}

        if arm == "A4":
            for rd in range(1, MAX_ROUNDS):
                crit = self._critic(P.REFLECT_TEXT_SYSTEM, text, profile, clauses, data, None, log, self.model)
                rounds[-1]["critic"] = crit
                emit("critic", round=rd - 1, critic=crit)
                if not crit:
                    break
                data = self._revise(msgs, data, crit, log, rd) or data
                rounds.append({"round": rd, "assessment": data, "issues": [], "critic": []})
                emit("assessment", round=rd, assessment=data)

        if arm in ("A5", "A6", "A5x", "A7"):
            critic_model = self.critic_model if arm == "A5x" else self.model
            for rd in range(MAX_ROUNDS):
                a, v_issues, info = verify(data, text, retrieved, self.manifest)
                v_dicts = [i.to_dict() for i in v_issues]
                rounds[-1]["issues"] = v_dicts
                emit("verifier", round=rd, issues=v_dicts)
                all_issues = list(v_dicts)
                if arm != "A6" and a is not None:
                    crit = self._critic(P.CRITIC_GROUNDED_SYSTEM, text, profile, clauses, data, v_dicts, log,
                                        critic_model)
                    kept = []
                    for c in crit:
                        why = self._check_critic_issue(c, retrieved, data)
                        c["accepted"] = why is None
                        c["rejected_reason"] = why
                        if why is None:
                            kept.append({"check": "critic", "type": c.get("type"), "parameter": c.get("parameter"),
                                         "detail": c.get("explanation", ""), "clause_id": c.get("clause_id"),
                                         "quote": c.get("quote")})
                    rounds[-1]["critic"] = crit
                    emit("critic", round=rd, critic=crit)
                    all_issues += kept
                final_status = info.get("status", {}) if a is not None else {}
                if not all_issues:
                    break
                if rd == MAX_ROUNDS - 1:
                    escalated = True
                    break
                new = self._revise(msgs, data, all_issues, log, rd + 1)
                data = new if new is not None else data
                rounds.append({"round": rd + 1, "assessment": data, "issues": [], "critic": []})
                emit("assessment", round=rd + 1, assessment=data)

        # ---------------------------------------------------------------- finalise
        try:
            a = Assessment.model_validate(data) if data else None
        except Exception:
            a = None
        confirmed, fixes = [], {}
        if a is not None:
            if arm in ("A5", "A6", "A5x", "A7"):
                _, _, info = verify(data, text, retrieved, self.manifest)
                final_status = info.get("status", {})
            for i, f in enumerate(a.findings):
                if f.verdict != "violation":
                    continue
                st = final_status.get(i, "unchecked") if arm in ("A5", "A6", "A5x", "A7") else "unchecked"
                d = f.model_dump()
                d["status"] = st
                if st == "unverified":
                    continue  # unverified findings never count as confirmed violations
                confirmed.append(d)
                if f.parameter in SECURITY_PARAMS and f.fix_value not in (None, "", []):
                    v = _norm(f.fix_value)
                    if f.parameter.endswith("_algorithms") and not isinstance(v, list):
                        v = [v]
                    if not f.parameter.endswith("_algorithms") and isinstance(v, list):
                        v = v[0] if v else ""
                    fixes[f.parameter] = v
        if arm == "A7" and confirmed:
            from ..repair.smt import repair_from_findings
            rep = repair_from_findings(text, confirmed, emergency=profile.emergency_unauth_supported)
            if rep is not None:
                fixes = rep["fixes"]
        patched, _ = apply_fixes(text, {k: (v if isinstance(v, list) else v) for k, v in fixes.items()}) \
            if fixes else (text, [])
        pred = sorted({f["parameter"] for f in confirmed if f["parameter"] in SECURITY_PARAMS})
        emit("final", predicted=pred, fixes=fixes, escalated=escalated)
        return RunResult(arm, cfg_id, profile.__dict__, self.model if arm != "A5x" else f"{self.model}+{self.critic_model}",
                         data, pred, confirmed, fixes, patched, unified_diff(text, patched), escalated,
                         rounds, [c.clause_id for c in clauses], queries, log.calls,
                         time.time() - t0, log.tokens,
                         None if data is not None else (log.calls[-1].get("error") if log.calls else "no output"))
