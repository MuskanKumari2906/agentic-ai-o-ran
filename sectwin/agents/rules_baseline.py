"""Arm A0: naive rule-based literal scanner (no LLM, no profile awareness).

This is the "short script" of gap G5: it flags literal values that look insecure. It does
not know deployment profiles, so it over-flags decoys (nea0 under the standards-minimum
profile, drb_integrity = "no", interfaces left unprotected inside a trusted domain) and
cannot reason about priority order beyond literal presence.

The same scanner is used by verifier check C5 to re-scan a corrected file. It is NOT the
oracle in sectwin/conf/security.py.
"""
from __future__ import annotations

from ..conf.security import SecurityView, security_view
from ..kb.clauses import BY_ID

# parameter -> (predicate on value, clause_id, fix)
def _has(v, tok):
    return tok in [str(x).lower() for x in v] if isinstance(v, list) else str(v).lower() == tok


LITERAL_RULES = [
    ("ciphering_algorithms", lambda v: _has(v, "nea0"), "TS33.501-D.1",
     lambda v: [a for a in v if a != "nea0"] or ["nea2"]),
    ("integrity_algorithms", lambda v: _has(v, "nia0") or not v, "TS33.501-D.1",
     lambda v: [a for a in (v or []) if a != "nia0"] or ["nia2"]),
    ("drb_ciphering", lambda v: str(v).lower() == "no", "TS33.501-5.3.2", lambda v: "yes"),
    ("drb_integrity", lambda v: str(v).lower() == "no", "TS33.501-5.3.3", lambda v: "yes"),
    ("f1c_protection", lambda v: str(v).lower() == "none", "TS33.501-9.8", lambda v: "ipsec"),
    ("n2_protection", lambda v: str(v).lower() == "none", "TS33.501-9.2", lambda v: "ipsec"),
    ("n3_protection", lambda v: str(v).lower() == "none", "TS33.501-9.3", lambda v: "ipsec"),
    ("xn_protection", lambda v: str(v).lower() == "none", "TS33.501-9.4", lambda v: "ipsec"),
    ("e2_protection", lambda v: str(v).lower() == "none", "ORAN-WG11-E2-1", lambda v: "ipsec"),
    ("o1_transport", lambda v: str(v).lower() == "netconf_plain", "ORAN-WG11-O1-1", lambda v: "netconf_tls"),
    ("tls_min_version", lambda v: str(v) in ("1.0", "1.1"), "ORAN-WG11-TLS-1", lambda v: "1.2"),
]


def scan(sec: SecurityView) -> list[dict]:
    """Return literal issues: [{parameter, value, line, clause_id, fix_value}]"""
    out = []
    for p, pred, clause, fix in LITERAL_RULES:
        v = sec.get(p)
        if v is None:
            continue
        try:
            hit = pred(v)
        except Exception:
            hit = False
        if hit:
            out.append({"parameter": p, "value": v, "line": sec.lines.get(p), "clause_id": clause,
                        "fix_value": fix(v)})
    return out


def scan_text(text: str) -> list[dict]:
    return scan(security_view(text))


def assess_a0(text: str) -> dict:
    """A0 output in the common Assessment shape."""
    from ..kb.clauses import normative_level
    findings = []
    for iss in scan_text(text):
        cl = BY_ID[iss["clause_id"]]
        quote = cl.sentences()[0]
        for s in cl.sentences():
            if normative_level(s) in ("shall", "shall_not"):
                quote = s
                break
        findings.append({
            "parameter": iss["parameter"], "line": iss["line"], "value": iss["value"],
            "verdict": "violation", "clause_id": iss["clause_id"], "quote": quote,
            "normative_level": normative_level(quote), "reason": "literal rule match",
            "fix_value": iss["fix_value"], "status": "confirmed"})
    from ..conf.security import SECURITY_PARAMS
    return {"assessed_parameters": list(SECURITY_PARAMS), "findings": findings,
            "overall": "non_compliant" if findings else "compliant"}
