"""Security view of a gNB configuration, deployment profiles, and the oracle policy.

The oracle (``evaluate``) is the ground truth used to LABEL the dataset and to SCORE
the arms. It is never shown to, or called by, any arm under test (A0-A6). The
verifier's re-scan (check C5) deliberately uses the naive literal scanner from
``sectwin.agents.rules_baseline`` instead, so no ground truth leaks into an arm.

Rule provenance
---------------
* 3GPP TS 33.501 rules are paraphrases read through a third-party mirror and are
  marked UNVERIFIED until checked against the official text (see proposal, Appendix B).
* O-RAN WG11 rules are paraphrased at requirement level and also UNVERIFIED.
* OSB-* rules come from the project's own *Operator Security Baseline*, a synthetic,
  explicitly PROPOSED operator policy that models a stricter operator.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Literal

from .libconf import ParsedConfig, parse

CIPHER_ALGS = ["nea0", "nea1", "nea2", "nea3"]
INTEG_ALGS = ["nia0", "nia1", "nia2", "nia3"]

# path in the config file -> short parameter name used everywhere else
PARAM_PATHS = {
    "ciphering_algorithms": "security.ciphering_algorithms",
    "integrity_algorithms": "security.integrity_algorithms",
    "drb_ciphering": "security.drb_ciphering",
    "drb_integrity": "security.drb_integrity",
    "f1c_protection": "interface_security.f1c_protection",
    "n2_protection": "interface_security.n2_protection",
    "n3_protection": "interface_security.n3_protection",
    "xn_protection": "interface_security.xn_protection",
    "e2_protection": "interface_security.e2_protection",
    "o1_transport": "interface_security.o1_transport",
    "tls_min_version": "interface_security.tls_min_version",
}
SECURITY_PARAMS = list(PARAM_PATHS)

ALLOWED_VALUES = {
    "drb_ciphering": ["yes", "no"],
    "drb_integrity": ["yes", "no"],
    "f1c_protection": ["dtls", "ipsec", "none"],
    "n2_protection": ["dtls", "ipsec", "none"],
    "n3_protection": ["ipsec", "none"],
    "xn_protection": ["dtls", "ipsec", "none"],
    "e2_protection": ["ipsec", "none"],
    "o1_transport": ["netconf_ssh", "netconf_tls", "netconf_plain"],
    "tls_min_version": ["1.0", "1.1", "1.2", "1.3"],
}

Baseline = Literal["standards_minimum", "operator_hardened"]


@dataclass(frozen=True)
class Profile:
    emergency_unauth_supported: bool = False
    baseline: Baseline = "standards_minimum"

    def key(self) -> str:
        return f"{'emerg' if self.emergency_unauth_supported else 'noemerg'}-{self.baseline}"

    def describe(self) -> str:
        e = ("unauthenticated emergency sessions ARE a regulatory requirement"
             if self.emergency_unauth_supported else
             "unauthenticated emergency sessions are NOT a regulatory requirement")
        b = ("only mandatory 3GPP / O-RAN requirements apply"
             if self.baseline == "standards_minimum" else
             "the Operator Security Baseline (OSB) also applies")
        return f"{e}; {b}"


PROFILES = [Profile(e, b) for e in (False, True) for b in ("standards_minimum", "operator_hardened")]


@dataclass
class SecurityView:
    values: dict           # param -> value (list for algorithm lists, str otherwise, None if absent)
    lines: dict            # param -> line number (None if absent)

    def get(self, p):
        return self.values.get(p)


def security_view(cfg: ParsedConfig | str) -> SecurityView:
    if isinstance(cfg, str):
        cfg = parse(cfg)
    vals, lines = {}, {}
    for p, path in PARAM_PATHS.items():
        s = cfg.find(path)
        vals[p] = s.value if s else None
        lines[p] = s.line if s else None
    return SecurityView(vals, lines)


@dataclass
class Reason:
    rule_id: str
    clause_ids: list[str]
    text: str
    severity: Literal["critical", "high", "medium", "low"]


@dataclass
class ParamLabel:
    parameter: str
    value: object
    line: int | None
    verdict: Literal["violation", "compliant"]
    reasons: list[Reason] = field(default_factory=list)
    governing_clauses: list[str] = field(default_factory=list)

    def to_dict(self):
        d = asdict(self)
        return d


def _lst(v):
    if v is None:
        return []
    return [str(x).lower() for x in v] if isinstance(v, list) else [str(v).lower()]


def evaluate(sec: SecurityView, profile: Profile) -> dict[str, ParamLabel]:
    """Oracle: per-parameter verdicts with reasons and governing clauses."""
    emerg = profile.emergency_unauth_supported
    hard = profile.baseline == "operator_hardened"
    out: dict[str, ParamLabel] = {}

    def lab(p, governing):
        out[p] = ParamLabel(p, sec.get(p), sec.lines.get(p), "compliant", [], governing)
        return out[p]

    def bad(label: ParamLabel, rule, clauses, text, sev):
        label.verdict = "violation"
        label.reasons.append(Reason(rule, clauses, text, sev))

    # --- integrity algorithms (RRC) -------------------------------------------------
    ia = _lst(sec.get("integrity_algorithms"))
    L = lab("integrity_algorithms", ["TS33.501-5.3.3", "TS33.501-D.1", "TS33.501-6.7.3"])
    real_ia = [a for a in ia if a in ("nia1", "nia2", "nia3")]
    if not real_ia:
        bad(L, "R-RRC-INTEGRITY", ["TS33.501-5.3.3"],
            "No non-null integrity algorithm is configured, so RRC signalling cannot be integrity protected.",
            "critical")
    if "nia0" in ia and not emerg:
        bad(L, "R-NIA0-DISABLED", ["TS33.501-5.3.3", "TS33.501-D.1"],
            "NIA0 is enabled although unauthenticated emergency sessions are not a regulatory requirement.",
            "high")
    if ia and ia[0] == "nia0" and emerg and real_ia:
        bad(L, "R-NIA0-PRIORITY", ["TS33.501-D.1", "TS33.501-6.7.3"],
            "NIA0 has the highest priority, so authenticated UEs would be assigned NIA0 for RRC signalling.",
            "high")
    if hard and real_ia and real_ia[0] == "nia1":
        # OSB-3: prefer AES/ZUC-based algorithms over SNOW 3G as first choice
        bad(L, "OSB-3", ["OSB-3"],
            "Operator baseline requires 128-NIA2 or 128-NIA3 as the highest-priority integrity algorithm.",
            "low")

    # --- ciphering algorithms ---------------------------------------------------------
    ca = _lst(sec.get("ciphering_algorithms"))
    L = lab("ciphering_algorithms", ["TS33.501-5.3.2", "OSB-1"])
    if hard:
        if "nea0" in ca and not emerg:
            bad(L, "OSB-1", ["OSB-1"],
                "Operator baseline forbids NEA0 when unauthenticated emergency sessions are not required.",
                "high")
        elif ca and ca[0] == "nea0":
            bad(L, "OSB-1", ["OSB-1"],
                "Operator baseline forbids NEA0 as the highest-priority ciphering algorithm.", "high")
        real_ca = [a for a in ca if a != "nea0"]
        if not real_ca:
            bad(L, "OSB-1", ["OSB-1"], "No non-null ciphering algorithm is configured.", "critical")
        elif real_ca[0] == "nea1":
            bad(L, "OSB-3", ["OSB-3"],
                "Operator baseline requires 128-NEA2 or 128-NEA3 as the highest-priority ciphering algorithm.",
                "low")

    # --- DRB switches -------------------------------------------------------------------
    L = lab("drb_ciphering", ["TS33.501-5.3.2", "OSB-2"])
    if hard and str(sec.get("drb_ciphering")).lower() == "no":
        bad(L, "OSB-2", ["OSB-2"], "Operator baseline requires ciphering of user-plane data radio bearers.",
            "high")
    # drb_integrity: user-plane integrity is optional to use in TS 33.501 5.3.3, and the
    # OSB leaves it to slice policy. "no" is therefore compliant in every profile (decoy).
    lab("drb_integrity", ["TS33.501-5.3.3"])

    # --- interfaces ----------------------------------------------------------------------
    for p, clause, osb in [("f1c_protection", "TS33.501-9.8", "OSB-4"),
                           ("n2_protection", "TS33.501-9.2", "OSB-4"),
                           ("n3_protection", "TS33.501-9.3", "OSB-4"),
                           ("xn_protection", "TS33.501-9.4", "OSB-4"),
                           ("e2_protection", "ORAN-WG11-E2-1", "OSB-4")]:
        L = lab(p, [clause, osb])
        if hard and str(sec.get(p)).lower() == "none":
            bad(L, osb, [osb, clause],
                f"Operator baseline requires cryptographic protection on this interface ({p}).", "medium")

    L = lab("o1_transport", ["ORAN-WG11-O1-1"])
    if str(sec.get("o1_transport")).lower() == "netconf_plain":
        bad(L, "R-O1-SECURE", ["ORAN-WG11-O1-1"],
            "O1 management traffic must use NETCONF over SSH or TLS, not plaintext.", "critical")

    L = lab("tls_min_version", ["ORAN-WG11-TLS-1", "OSB-5"])
    v = str(sec.get("tls_min_version"))
    if v in ("1.0", "1.1"):
        bad(L, "R-TLS-12", ["ORAN-WG11-TLS-1"], "TLS versions below 1.2 must not be negotiated.", "high")
    if hard and v in ("1.0", "1.1", "1.2"):
        bad(L, "OSB-5", ["OSB-5"], "Operator baseline requires TLS 1.3 as the minimum version.", "low")

    return out


def summarize(labels: dict[str, ParamLabel]) -> dict:
    viol = [p for p, l in labels.items() if l.verdict == "violation"]
    return {"compliant": not viol, "violations": viol}


def evaluate_text(text: str, profile: Profile):
    return evaluate(security_view(text), profile)
