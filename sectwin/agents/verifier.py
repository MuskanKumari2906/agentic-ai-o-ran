"""Stage 1 of the Reflection Agent: deterministic verifier, checks C1-C5. No LLM, no oracle.

C1 schema        output validates against the Assessment schema
C2 grounding     flagged parameter exists in the parsed file with the stated value
C3 citation      clause was retrieved, its chunk hash matches the trusted manifest,
                 and the quote appears in the clause text (fuzzy >= QUOTE_THRESHOLD)
C4 strength      a violation must rest on a "shall"/"shall not" sentence that is about
                 USE (not "shall support"/"shall implement") and mentions the parameter's subject
C5 fix           every violation has a fix; values are legal; the patched file parses;
                 only flagged lines change; the literal re-scan finds no new issue
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict

from pydantic import ValidationError
from rapidfuzz import fuzz

from ..conf.libconf import is_valid
from ..conf.patch import apply_fixes, changed_lines
from ..conf.security import ALLOWED_VALUES, CIPHER_ALGS, INTEG_ALGS, PARAM_PATHS, security_view
from ..kb.clauses import Clause, normative_level
from .rules_baseline import scan_text
from .schema import Assessment

QUOTE_THRESHOLD = 90

SUBJECT = {
    "ciphering_algorithms": r"nea|cipher|confidential",
    "integrity_algorithms": r"nia|integrity",
    "drb_ciphering": r"cipher|confidential",
    "drb_integrity": r"integrity|nia",
    "f1c_protection": r"\bf1",
    "n2_protection": r"\bn2\b",
    "n3_protection": r"\bn3\b",
    "xn_protection": r"\bxn",
    "e2_protection": r"\be2\b",
    "o1_transport": r"\bo1\b|netconf|management",
    "tls_min_version": r"\btls\b",
}


@dataclass
class Issue:
    check: str
    type: str
    parameter: str
    detail: str

    def to_dict(self):
        return asdict(self)


def _norm(v):
    if isinstance(v, list):
        return [str(x).strip().lower() for x in v]
    if isinstance(v, str):
        s = v.strip().strip("()").replace('"', "").replace("'", "")
        if "," in s:
            return [x.strip().lower() for x in s.split(",") if x.strip()]
        return s.lower()
    return v


def _same(a, b) -> bool:
    a, b = _norm(a), _norm(b)
    if isinstance(a, list) and not isinstance(b, list):
        b = [b]
    if isinstance(b, list) and not isinstance(a, list):
        a = [a]
    return a == b


def legal_value(p: str, v) -> bool:
    v = _norm(v)
    if p == "ciphering_algorithms":
        return isinstance(v, list) and len(v) > 0 and all(x in CIPHER_ALGS for x in v)
    if p == "integrity_algorithms":
        return (isinstance(v, list) and len(v) > 0 and all(x in INTEG_ALGS for x in v)
                and any(x != "nia0" for x in v))
    if isinstance(v, list):
        return False
    return v in ALLOWED_VALUES.get(p, [])


ALG_RE = re.compile(r"\b(?:128-)?(nea[0-3]|nia[0-3])\b")
SECURE_VALUES = {"yes", "ipsec", "dtls", "netconf_ssh", "netconf_tls", "1.3"}


def c4_check(parameter: str, quote: str, value=None) -> str | None:
    """Normative strength, subject and applicability of the sentence a violation rests on.

    Purely linguistic / structural checks against the cited sentence and the current value;
    no policy knowledge. ``value`` is the parameter's current value when known."""
    lvl = normative_level(quote or "")
    q = (quote or "").lower()
    if lvl not in ("shall", "shall_not"):
        return f"a violation cannot rest on a '{lvl}' sentence"
    if lvl == "shall" and re.search(r"shall (support|implement)|required to implement|shall be supported", q):
        return "quote states a capability requirement (shall support / implement), not a usage requirement"
    if parameter in SUBJECT and not re.search(SUBJECT[parameter], q):
        return "quoted requirement is not about this parameter"
    algs_in_quote = set(ALG_RE.findall(q))
    if value is not None:
        v = _norm(value)
        if parameter.endswith("_algorithms"):
            vals = set(v) if isinstance(v, list) else {v}
            if algs_in_quote and not (algs_in_quote & vals) and lvl == "shall_not":
                return "the quote forbids algorithms that are not configured in this parameter"
        else:
            if algs_in_quote and parameter in ("drb_ciphering", "drb_integrity"):
                return "the quote concerns algorithm selection, not this on/off switch"
            if re.match(r"\s*(when|if|where)\b[^.]*\b(is|are) used", q) and str(v) == "no":
                return "the requirement applies only when the feature is used; it is switched off here"
            if lvl == "shall" and str(v) in SECURE_VALUES and not re.search(r"tls 1\.3|minimum", q):
                return "the current value already satisfies this requirement"
    return None


def c1_schema(raw: dict | None) -> tuple[Assessment | None, list[Issue]]:
    if raw is None:
        return None, [Issue("C1", "SchemaError", "-", "output is not valid JSON")]
    try:
        return Assessment.model_validate(raw), []
    except ValidationError as e:
        return None, [Issue("C1", "SchemaError", "-", str(e.errors()[:3]))]


def verify(raw: dict | None, text: str, retrieved: dict[str, Clause] | None,
           manifest: dict[str, str], check_retrieved: bool = True) -> tuple[Assessment | None, list[Issue], dict]:
    """Run C1-C5. Returns (assessment, issues, per-finding status map)."""
    a, issues = c1_schema(raw)
    if a is None:
        return None, issues, {}
    sec = security_view(text)
    per: dict[int, list[Issue]] = {}

    for i, f in enumerate(a.findings):
        fi: list[Issue] = []
        if f.verdict != "violation":
            per[i] = fi
            continue
        # C2 -----------------------------------------------------------------
        if f.parameter not in PARAM_PATHS:
            fi.append(Issue("C2", "ParamNotFound", f.parameter, "not a security parameter of this file"))
        else:
            actual = sec.get(f.parameter)
            if actual is None:
                fi.append(Issue("C2", "ParamNotFound", f.parameter, "parameter is absent from the file"))
            elif f.value is not None and not _same(f.value, actual):
                fi.append(Issue("C2", "ParamNotFound", f.parameter,
                                f"stated value {f.value!r} differs from file value {actual!r}"))
            elif f.line and sec.lines.get(f.parameter) and abs(f.line - sec.lines[f.parameter]) > 2:
                fi.append(Issue("C2", "ParamNotFound", f.parameter,
                                f"stated line {f.line}, actual line {sec.lines[f.parameter]}"))
        # C3 -----------------------------------------------------------------
        chunk = (retrieved or {}).get(f.clause_id)
        if check_retrieved and chunk is None:
            fi.append(Issue("C3", "UnsupportedCitation", f.parameter,
                            f"clause {f.clause_id} was not among the retrieved clauses"))
        elif chunk is not None and manifest.get(f.clause_id) != chunk.sha256:
            fi.append(Issue("C3", "UnsupportedCitation", f.parameter,
                            f"clause {f.clause_id} failed the provenance check (hash not in trusted manifest)"))
        elif chunk is not None and fuzz.partial_ratio(f.quote.lower(), chunk.text.lower()) < QUOTE_THRESHOLD:
            fi.append(Issue("C3", "QuoteNotFound", f.parameter,
                            f"quote not found in {f.clause_id}"))
        # C4 -----------------------------------------------------------------
        why = c4_check(f.parameter, f.quote, sec.get(f.parameter))
        if why:
            fi.append(Issue("C4", "WrongStrength", f.parameter, why))
        per[i] = fi
        issues.extend(fi)

    # C5 ---------------------------------------------------------------------
    viol = [f for f in a.findings if f.verdict == "violation" and f.parameter in PARAM_PATHS]
    fixes = {}
    for f in viol:
        if f.fix_value is None or f.fix_value == "" or f.fix_value == []:
            iss = Issue("C5", "BadFix", f.parameter, "no fix proposed for a violation")
            issues.append(iss)
            per[a.findings.index(f)].append(iss)
        elif not legal_value(f.parameter, f.fix_value):
            iss = Issue("C5", "BadFix", f.parameter, f"fix value {f.fix_value!r} is not a legal value")
            issues.append(iss)
            per[a.findings.index(f)].append(iss)
        else:
            fixes[f.parameter] = _norm(f.fix_value)
    patched, errs = apply_fixes(text, fixes)
    for e in errs:
        issues.append(Issue("C5", "BadFix", "-", e))
    ok, err = is_valid(patched)
    if not ok:
        issues.append(Issue("C5", "BadFix", "-", f"patched file does not parse: {err}"))
    flagged_lines = {sec.lines[p] for p in fixes if sec.lines.get(p)}
    extra = [ln for ln in changed_lines(text, patched) if ln not in flagged_lines]
    if extra:
        issues.append(Issue("C5", "OverChange", "-", f"lines changed outside flagged parameters: {extra[:5]}"))
    before = {i["parameter"] for i in scan_text(text)}
    after = scan_text(patched) if ok else []
    for iss in after:
        if iss["parameter"] in fixes:
            issues.append(Issue("C5", "BadFix", iss["parameter"], "fix leaves a literal insecure value"))
        elif iss["parameter"] not in before:
            issues.append(Issue("C5", "BadFix", iss["parameter"], "fix introduces a new literal issue"))

    status = {i: ("confirmed" if not per.get(i) else "unverified") for i in range(len(a.findings))}
    return a, issues, {"status": status, "patched": patched, "fixes": fixes}
