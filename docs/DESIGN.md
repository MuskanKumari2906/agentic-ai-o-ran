# Design

## 1. Research question (unchanged from the proposal)

Does a Reflection Agent improve security-compliance assessment of O-RAN gNB configuration files beyond
(a) a rule-based checker, (b) ordinary RAG and (c) a single-agent agentic-RAG assessor? If so, does the
gain come from the LLM critic or from deterministic verification of the evidence?

The build adds two questions the proposal listed as extensions:

* **Network impact:** does a better compliance agent reduce real exposure in a running network
  (null-ciphered traffic, spoofable RRC, successful attacks), and what does remediation cost in service?
* **Remediation timing:** can a learned policy schedule fixes better than fixed rules?

## 2. Ground truth and leakage

`sectwin/conf/security.py::evaluate` is the oracle. It labels the dataset and scores results and is never
called by an arm. Specifically:

* A0 is a naive literal scanner (`agents/rules_baseline.py`), deliberately profile-unaware.
* Verifier check C5 re-scans a corrected file with the same naive scanner, not the oracle.
* A7's SMT repair compiles only the clauses cited in the arm's own confirmed findings.
* The oracle-driven SMT repair is used only to score fix optimality and in the twin's manual audit.

## 3. Deployment profiles

A profile has two dimensions:

* `emergency_unauth_supported`, from TS 33.501: NIA0 must be disabled unless unauthenticated emergency
  sessions are a regulatory requirement.
* `baseline` = `standards_minimum` | `operator_hardened`. The hardened baseline adds the project's
  synthetic Operator Security Baseline (OSB-1..5): no NEA0, DRB ciphering on, AES/ZUC first,
  interfaces protected, TLS 1.3.

This makes several verdicts context-dependent. `nea0` is permitted under standards-minimum (ciphering is
optional to use) but a violation under the hardened baseline. `drb_integrity = "no"` is compliant
everywhere, because user-plane integrity is optional; this is the G4 decoy from the proposal.

## 4. Reflection Agent

Stage 1, deterministic verifier (`agents/verifier.py`):

| Check | What it verifies |
|---|---|
| C1 | output validates against the Assessment schema |
| C2 | flagged parameter exists, with the stated value and line |
| C3 | cited clause was retrieved, its hash matches the trusted manifest (provenance), quote found (fuzzy >= 90) |
| C4 | the quote is a `shall` / `shall not` usage requirement (not "shall support"), is about this parameter, and applies to the current value (conditional "when ... is used", algorithm-specific quotes against on/off switches, quotes about algorithms not configured, requirements already met) |
| C5 | every violation has a legal fix, the patched file parses, only flagged lines change, the literal re-scan finds nothing new |

Stage 2, LLM critic: it receives the parsed parameters, the findings and the C1-C5 results, and reports
`MissedViolation` / `ScopeError` claims. Each claim must carry a clause and quote, and passes C3 and C4
before it is fed back. A finding that is still unverified after N = 3 rounds is dropped and the case is
escalated; it never counts as a confirmed violation.

## 5. Arms

| Arm | RAG | Query gen | LLM reflection | Verifier | LLM critic | Fix |
|---|---|---|---|---|---|---|
| A0 | | | | | | rule |
| A1 | | | | | | LLM |
| A2 | yes | | | | | LLM |
| A3 | yes | yes | | | | LLM |
| A4 | yes | yes | yes | | | LLM |
| A5 | yes | yes | | yes | yes | LLM |
| A6 | yes | yes | | yes | | LLM |
| A7 | yes | yes | | yes | yes | SMT |
| A5x | as A5, critic = Llama-3.1-8B |

All LLM arms receive the same parsed parameter table and legal-value list, so differences come from the
component under test.

## 6. Twin

See `sectwin/twin/radio.py` and `engine.py` docstrings. Key modelling choices:

* TR 38.901 UMa path loss (LOS-probability-weighted), 6 dB shadowing with 50 m decorrelation and 0.5
  inter-site correlation, 3GPP sector pattern, 49 dBm per 100 MHz sector at 3.5 GHz.
* Link abstraction: 0.75 * Shannon, capped at 7.4 b/s/Hz, rank 2 above 12 dB, 14 % overhead.
* Water-filling time-share scheduler per cell; TCP-limited queues for elastic traffic.
* AS security: the gNB selects the first algorithm in its configured list that the UE supports
  (TS 33.501 6.7.3), at attach and at handover. 20 % of UEs (configurable) model non-conformant basebands
  that accept an SMC selecting NIA0; conformant UEs reject it and fail to attach to that gNB.
* Attackers: passive sniffer (captures unciphered UP within radius), RRC injector (forged RRC release
  succeeds only against UEs on NIA0 and denies service for 15 s), backhaul tap (N3 without IPsec), and O1
  MITM (pushes malicious configs to gNBs whose O1 is plaintext).
* Remediation: a pushed fix restarts security on the gNB (20 s outage for algorithm/DRB changes, 5 s for
  interface changes).

## 7. Known limitations

* Clause texts are paraphrases. The C3 quote check works on whatever text is in the KB, so replacing
  the KB with official text requires no code change.
* The twin is a system-level simulator, not a protocol stack. Absolute KPIs are indicative; comparisons
  between arms and policies on identical seeds are the meaningful output.
* The 7B model is far smaller than the models used in [1]; absolute accuracy is not comparable to [1].
