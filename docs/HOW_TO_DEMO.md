# How to understand and demo SecTwin

This guide assumes no background. Read part 1 once (10 minutes), then follow part 2 when presenting.

---

## Part 1. What the project is, in plain words

### The problem

A 5G base station (a **gNB**) is a computer program with a long configuration file. A few lines in that
file decide how well users are protected, for example:

* `ciphering_algorithms`: which encryption to use. `nea0` means **no encryption**.
* `integrity_algorithms`: which tamper-protection to use. `nia0` means **no protection**, so an attacker
  can forge control messages.
* settings for the links between network boxes (F1, N2, N3, Xn, E2) and the management link (O1).

In **O-RAN**, many vendors and automated controllers change these files all the time, so a mistake can
appear at any moment. Checking every file by hand against the security standards (3GPP TS 33.501, O-RAN
WG11) does not scale.

### The idea

Use an **AI agent** (a language model) to read the file and the standards and say "this line breaks
this rule, here is the fix". The weakness: language models make things up. They flag settings that are
fine, cite rules that do not say what they claim, and propose broken fixes.

The proposal's question: **does a "Reflection Agent" that double-checks the AI's answer make it reliable?**

### What was built (four parts)

1. **Compliance agents (the AI).** Nine versions ("arms", A0 to A7 and A5x), from a simple
   find-the-bad-word script (A0) to the AI with a checker (A5). The key part is the **verifier**: five
   checks done by ordinary code, not by the AI:
   * C1: is the answer in the right format?
   * C2: does the setting really exist in the file with that value?
   * C3: does the quoted rule really exist and say those words? (also detects tampered rules)
   * C4: is the rule a real "shall / shall not" requirement that applies here?
   * C5: is the proposed fix valid, and does it change only what it should?

   Anything the AI says that fails a check is sent back to it; if it still fails, it is thrown away.
   **A7** additionally replaces the AI's fix with one computed by a solver (z3), which finds the smallest
   correct change.
2. **Network digital twin (the simulation).** A simulated city-sized 5G network: base stations, phones
   moving around, video/web/voice traffic, handovers, throughput and delay. Every base station runs a real
   configuration file, so a bad setting has visible effects: unencrypted traffic, forged messages, users
   kicked off. Attackers and random configuration changes are built in, and the compliance agent watches
   the network and pushes fixes, like a real operations centre.
3. **Learning when to fix (RL).** Applying a fix restarts part of a base station, which disturbs users. A
   reinforcement-learning policy learned when to fix (now for severe problems, at night for minor ones).
4. **The dashboard.** A network-operations-centre style web page that shows all of the above live.

### What the experiments found (the headline)

* The AI alone flags about six fine settings for every real problem.
* **Checking its evidence with code fixes most of that**: the verifier-grounded agent (A5) was exactly
  right on 18 files where the plain AI agent (A3) was wrong, and never the other way round.
* **Letting the AI criticise itself (A4) did not help** in a measurable way. So the value is in the
  code checks, not in "AI checking AI". This matches the proposal's hypotheses.
* **AI-written fixes are dangerous**: in the simulated network they left base stations insecure for
  longer than doing nothing. The solver-made fixes (A7) were the safest.
* Limits: a small 7B model, a synthetic dataset, paraphrased rule texts, simulated network. These are
  pilot results; the report says so.

### Words you will hear

| Word | Meaning |
|---|---|
| gNB | 5G base station |
| UE | a phone or device |
| SMO / Non-RT RIC | the O-RAN management layer where the compliance agent runs |
| O1 | the management link used to read and change configurations |
| NEA0 / NIA0 | "null" algorithms: no encryption / no integrity protection |
| RRC | control messages between phone and base station; forgeable if integrity is NIA0 |
| Profile | the deployment's rules: whether emergency calls without a SIM must work, and whether the operator's stricter baseline applies |
| Decoy | a setting that looks insecure but is allowed under the profile (tests over-flagging) |
| Arm | one version of the system in the experiment |
| Replay mode | the dashboard shows recorded results instead of calling the AI live |

---

## Part 2. The 10-minute demo (click by click)

Start the dashboard first (`run_demo.bat`, see docs/INSTALL.md). Replay mode is fine for the whole demo.

### Step 1. The network (Network topology page, 3 min)

1. Leave the scenario at its defaults (19 sites, 1500 UEs, Operator hardened, attackers on, agent A5,
   Replay) and press **Start simulation**. Choose speed **20x**.
2. Say: *"This is a simulated 5G network. Each hexagon is a cell, the triangles are base stations, the
   dots are phones. Every base station runs its own configuration file."*
3. Click a base station near the middle. In the right panel, under **Actions**, press **Malicious push via
   O1**. Say: *"An attacker on the management network just changed this base station's security settings."*
4. Point at: the cell turning red; **Unciphered UP** and **Spoofable RRC** counters rising; orange and red
   dots (phones without encryption / with forgeable messages); **HO DOWNGRADE** lines in the event log
   (phones losing encryption when they move into this cell).
5. Watch the **SMO compliance service** panel: *ASSESSING*, then *ASSESSED* with the agent's verdict next
   to the ground truth, then **FIX PUSHED** in the event log and the cell turning back to normal.
   Say: *"The agent detected it, proposed a fix, and the fix was pushed after a short approval delay."*

### Step 2. Inside the agent (Compliance console, 4 min)

1. Open **Compliance console**. Select **cfg-001** (a decoy: the file is actually fine).
2. Choose arm **A3** in the top-right box. Say: *"The plain AI agent claims three violations, all wrong."*
   The table on the left shows **FALSE POS.** for each.
3. Choose arm **A5**. Scroll the right panel: the AI's first answer had the same mistakes, then
   **Reflection, round 0** lists the verifier rejecting them, for example *"the quote concerns algorithm
   selection, not this on/off switch"*. The final result: no violations, **CORRECT**.
   Say: *"The code checks caught every false claim. This is the core result of the project."*
4. Select **cfg-024** (one real violation: the ciphering list allows NEA0). With **A5**, the violation is
   found correctly. Point at **Proposed change** (the AI's fix puts the weaker NEA1 first, which the
   operator policy forbids) and **Minimal repair (SMT, reference)** below it. Say: *"The AI found the
   problem but its fix is not quite right; the solver's fix is minimal and correct. That is arm A7."*

### Step 3. The evidence (Experiments page, 2 min)

1. Open **Experiments**. Point at the first table: F1 and exact match per arm, with confidence intervals.
2. Point at **Paired tests**: *"A5 vs A3: 18 to 0. A4 vs A3: not significant. The checker matters, not
   the AI's self-criticism."*
3. Scroll to the robustness and poisoning table: *"When we planted a fake rule, only the agent with the
   hash check refused to cite it."*

### Step 4. Trust (Audit trail, 1 min, only if you used "Run live")

Every live assessment is recorded in a chain where each entry contains the fingerprint (hash) of the one
before. **Verify chain** recomputes them; editing any old record would break the chain.

### If you have a GPU or an API key

In the Compliance console press **Run live** to watch the AI work in real time (each step appears as it
happens). Without one, the button explains that only recorded runs are available.

---

## Part 3. Questions you may get

**Is this a real network?** No. It is a simulator built for this project. Its radio model was checked
against ns-3 5G-LENA (a standard research simulator) on the same layout: the typical signal quality
matches within about 1-2 dB; the extremes differ, which the report states.

**Why not just use the simple script (A0)?** It is good at spotting obviously bad values, but it cannot
reason about the deployment profile: it never handled a decoy or a context-dependent file correctly. On
judging whole files exactly right, A5 beat it 15 to 3.

**Why is the accuracy so low (27% exact match)?** The experiments used a small 7-billion-parameter model
running on a laptop GPU, and the dataset was made deliberately hard. The study compares versions of the
system under identical conditions; the differences between them are the result.

**Did you use the official 3GPP text?** The rule texts are paraphrases written for the project and
are marked as such. The code needs no change to use the official sentences, but the experiments must then
be re-run.

**Where do the numbers come from?** Every number is computed from logged runs in the `results` folder;
`docs/SecTwin_Implementation_Report.pdf` explains the method and the limits.

**Does it need a GPU?** Not for the demo. A GPU (or an API key) is only needed to run the AI live.
