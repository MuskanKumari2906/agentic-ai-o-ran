# Panel demonstration script (about 12 minutes)

Start: `python -m uvicorn sectwin.api.server:app --port 8600`, open http://localhost:8600, Ollama running.

## 1. The problem, in the network (Network topology, 3 min)

1. Scenario panel: 19 gNB sites, 1500 UEs, profile *Operator hardened, no emergency requirement*,
   threats: sniffer, RRC injector, O1 MITM. Agent configuration **A5**, execution **Replay measured runs**,
   remediation **Immediate**. Press **Start simulation**, speed 20x.
2. Point out: every gNB runs a full OAI-style `gnb.conf`; the map shows sector load, UEs, attacker ranges.
3. Click a gNB, then **Malicious push via O1**. Its cell turns red, the KPI strip shows UEs on an
   unciphered user plane, the event log shows *HO DOWNGRADE* as UEs hand over into that cell, and the
   RRC injector starts succeeding against UEs on NIA0.
4. Wait for the SMO compliance service: *ASSESSING* -> *ASSESSED* -> *FIX PUSHED* (short outage, then green).
   The SMO panel compares the agent's verdict with ground truth.

## 2. How the agent decides (Compliance console, 4 min)

1. Open the configuration from the gNB panel (**Open in console**), or pick `cfg-001` (a decoy).
2. Select **A3** (agentic RAG): it reports `drb_integrity = "no"` and other compliant settings as
   violations. This is the over-flagging behaviour of a small model.
3. Select **A5**: the same round-0 findings, then **Reflection**: C4 rejects them ("the quote concerns
   algorithm selection, not this on/off switch", "requirement applies only when the feature is used").
   Critic claims show **ACCEPTED** / **REJECTED** with the evidence check.
4. Pick a non-compliant file and show the **Proposed change** against the **Minimal repair (SMT)**.
5. Optional: **Run live** to show the local LLM working end to end (40-120 s).

## 3. Evidence (Experiments, 3 min)

* E1 table: F1 with confidence intervals, citation correctness, fix correctness, reflection flips
  (wrong-to-right vs right-to-wrong), and cost per configuration.
* Category heat map: decoys and context pairs are where the arms differ.
* E2/E3: prompt injection in a config comment; poisoned clauses blocked by the provenance check.
* E4: the same 6-hour network run per arm, giving exposure, attacks and outage.
* E5/E6: the cost of UP integrity, and the RL scheduler against fixed policies.

## 4. Trust (Audit trail, 1 min)

Show the chained hashes and **Verify chain**. Every assessment from the console is recorded with the
config hash, model, retrieved clauses and fixes.

## Honest framing for questions

* The network is simulated (system-level twin, cross-checked against ns-3 5G-LENA SINR on the same
  layout), not OAI.
* Clause texts are paraphrases pending the official 3GPP / O-RAN text.
* Pilot scale: 45 test configurations; intervals are reported and unresolved differences are called so.
