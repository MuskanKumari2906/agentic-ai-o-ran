# Build log

Running record of what was built, decisions taken, and anything that did not work.
Newest entries at the bottom. Times are local (IST), 19-20 Oct 2026.

## Entry 1: environment and decisions

- Machine: Windows 11, Python 3.13, RTX 4060 Laptop (8 GB), Node 22, Docker available.
- No local LLM runtime was installed (only an empty `~/.ollama`). Installed **Ollama 0.40.5**
  via `winget` (official package, hash verified). Pulling `qwen2.5:7b-instruct` (primary
  model) and `llama3.1:8b` (second model family, used for the cross-family critic).
- Installed Python packages: `z3-solver`, `gymnasium`, `stable-baselines3`, `rank-bm25`.
- Project folder: `oran-sectwin/`.

Design decisions (see `docs/DESIGN.md` for the full rationale):

1. **Ground truth never leaks into an arm.** The oracle policy (`sectwin/conf/security.py`) labels
   the dataset and scores results only. The verifier's re-scan (C5) uses the naive literal
   scanner that is also arm A0, not the oracle. (This was issue 3 in the proposal review.)
2. **Profiles have two dimensions**: `emergency_unauth_supported` (from TS 33.501) and `baseline`
   = `standards_minimum` | `operator_hardened`. The hardened baseline is a synthetic,
   project-written *Operator Security Baseline* (clauses OSB-1..5). This makes the
   "is `nea0` a violation?" question context-dependent, which is the point of G4.
3. **`drb_integrity = "no"` is compliant in every profile** (user-plane integrity is optional to
   use). It is the dataset's main decoy, matching gap G4 in the proposal.
4. The OAI `security` block is reproduced as OAI ships it. An `interface_security` group is a
   clearly marked **sectwin extension** that models O-RAN / 3GPP interface protection (F1-C, N2,
   N3, Xn, E2, O1, TLS). OAI has no such block.

## Entry 2: config layer, knowledge base, dataset

- `sectwin/conf/libconf.py`: libconfig parser (groups, lists, arrays, scalars, comments) that
  returns every setting with its dotted path and line number. Used for C2 and C5.
- `sectwin/conf/template.py`: OAI-style `gnb.conf` renderer (abridged radio section, OAI's own
  security comments).
- `sectwin/conf/security.py`: security view and oracle with rule IDs, clause references, severity.
- `sectwin/kb/clauses.py`: 34 clauses (TS 33.501 paraphrases, O-RAN WG11 paraphrases, OSB policy,
  distractors) with SHA-256 per chunk and a trusted manifest. All 3GPP / O-RAN text is marked
  `paraphrase-unverified`.
- `sectwin/dataset/generate.py`: seeded dataset of **62 configs** (45 test / 17 dev) across clean,
  vendor-default (OAI sample values), single, multi, decoy, context-pair and noise categories.
  27 of 62 are non-compliant under their profile.

## Entry 3: agents, verifier, repair (19 Oct, 19:00-20:00)

- `sectwin/agents/`: Ollama client with on-disk cache (`runs/llm_cache`, makes runs resumable), JSON-schema
  structured outputs, prompts, the A0 literal scanner, the C1-C5 verifier, and the arm pipeline (A0-A7, A5x).
- `sectwin/repair/smt.py`: clause compiler + z3 minimal repair. Cost = algorithms added + removed + order
  flips. Verified: the oracle-driven repair makes all 62 configs compliant with minimal edits
  (e.g. `("nia2","nia0") -> ("nia2")`; under an emergency profile `("nea0") -> ("nea2","nea0")`).
- Retrieval switched from sentence-transformers to Ollama `nomic-embed-text`, because the miniconda
  environment has a torch/torchvision mismatch. Hybrid BM25 + dense with reciprocal-rank fusion.

Problems found in smoke tests and fixed:
1. Assessor JSON truncated at 1200 tokens once it reported all 11 parameters -> raised to 3000,
   compact output for compliant parameters, parse errors fed back to the model, new seed per round.
2. The 7B model proposed illegal values (`drb_ciphering = "nea2"`) -> legal-value table in the prompt
   (all LLM arms), C5 rejects illegal fixes.
3. Critic claims accepted too easily -> critic claims now pass C3 + full C4, and scope/verdict
   complaints must target an existing finding.
4. C4 was too weak ("When UP integrity is used, NIA0 shall not be used" passed for
   `drb_integrity = "no"`) -> added applicability checks: conditional "when ... is used" requirements,
   algorithm-specific quotes cited against on/off switches, quotes about algorithms not configured, and
   requirements already satisfied by the current value. Purely linguistic, no policy knowledge.

## Entry 4: network digital twin (20:00)

- `sectwin/twin/`: radio (hex layout, TR 38.901 UMa path loss, 3GPP sector pattern, correlated shadowing
  with 0.5 inter-site correlation, SINR, NR-like link abstraction), traffic (video, web, VoIP, IoT, bulk,
  FWA; diurnal profile; TCP-limited queues), A3 handover with L3 filtering and TTT, T310-style RLF,
  AS security selection from each gNB's actual config at attach and handover, attackers (passive sniffer,
  RRC injector, backhaul tap, O1 MITM that pushes malicious configs), config drift, SMO compliance
  service (replay or live), remediation with outage, periodic manual audit.
- Calibration iterations: handover ping-pong (58/h pedestrians) fixed with inter-site shadow correlation,
  4 dB A3 margin, L3 filter; RLF counted per episode with Qin hysteresis; traffic tuned so busy-hour
  mean sector load is ~37 %. Result: pedestrians ~28 HO/h, vehicles ~160 HO/h (one per ~280 m at
  500 m ISD), RLF ~3 % of handovers, p50/p95/p99 latency 5.9/5.9/136 ms.

## Entry 5: experiments launched, dashboard (20:00-21:00)

- Overnight runner `sectwin/eval/run_experiments.py` (resumable, sharded). Ollama restarted with
  `OLLAMA_NUM_PARALLEL=2` + flash attention via `scripts/serve_ollama.sh` (self-restarting); two
  supervised shards via `scripts/run_shard.sh`. NOTE: the Ollama tray app was closed for this; reopen
  it from the Start menu afterwards if wanted.
- Backend `sectwin/api/server.py` (FastAPI): dataset, KB, live assessments with step events, recorded
  runs, results, progress, hash-chained audit log, twin control + WebSocket stream.
- Dashboard `ui/` (React + TypeScript + ECharts, IBM Plex fonts bundled): Network topology (live map),
  Assurance, Compliance console, Audit trail, Experiments, Configs & clauses.
- First real signal (cfg-001, a decoy): A1-A3 report 3 false violations, A4 1, A5/A6 0 (correct).

## Entry 6: RL scheduler, E5, reporting (20:15-20:45)

- `sectwin/rl/`: remediation-scheduling Gymnasium environment calibrated from the twin, PPO (SB3, 400k
  steps, 142 s on CPU), baselines (immediate, maintenance window, severity threshold), in-twin policy.
  **E6 result (200 paired episodes):** PPO reward -138.0 vs severity-threshold -149.6 (gain +11.5,
  95% CI [8.3, 14.9], PPO better in 73.5% of episodes) and vs immediate -169.3 (gain +31.3, CI [29.5, 33.1]).
  PPO roughly halves the threshold policy's exposure (16.3 vs 26.5 UE-h) at equal disruption.
- **E5 result (busy hour, 19 sites, 1500 UEs):** UP integrity costs 0.29 percentage points of total goodput,
  raises VoIP header overhead from 6.5% to 9.9%, and adds 0.05 ms latency. N3 IPsec adds 0.1 ms.
- Twin: Parquet telemetry export (`Twin.export`, dashboard button, E4 runs saved under data/telemetry/),
  aggregated handover-downgrade events, RSRP recomputed only for moved UEs.
- Metrics: fix correctness now measured on non-compliant files only; new unnecessary-change rate on
  compliant files. Scores are recomputed from stored runs in `analyze.py`.
- Reporting: `scripts/make_results_md.py` (tables), `scripts/make_figures.py` (matplotlib),
  `scripts/report/build_report.js` (Word report, docx library) -> docs/SecTwin_Implementation_Report.docx.
- ns-3.48 + 5G-LENA v5.1 building in WSL Ubuntu (official GitLab sources) for radio cross-validation
  using the `3gpp-outdoor-calibration` example (UMa, 19 sites).
- Incident: experiment throughput dropped ~3x because the dashboard demo twin kept making live LLM calls
  and the ns-3 compile saturated the CPU. Demo twin stopped; compile reniced to 19.

## Entry 7: results night (21:00-01:40)

- **ns-3 cross-check** (ns-3.48 + 5G-LENA v5.1 in WSL, `cttc-nr-3gpp-calibration-user`): median per-UE SINR
  twin 3.9 dB vs ns-3 4.6 dB (default) / 5.6 dB (attach to closest). ns-3 has higher upper tail (beamforming
  arrays) and an unexplained low tail in every configuration; a 1x1 omni run was not like-for-like (no
  sectorisation). Recorded as an open item.
- **E1 repeat 0 complete** (360 runs). A5 vs A3 exact-match 10/0 (p = 0.002), A6 vs A3 8/0 (p = 0.008), A5 vs
  A4 8/0 (p = 0.008); A4 vs A3 and A5 vs A6 not resolved. Precision 0.15 -> 0.25 with verification; A0 F1 0.41.
- **E4 bug found and fixed:** the first E4 run was invalid because the O1 attacker's random draws depended on
  agent actions, so arms saw different drift/attack sequences. Events now use a separate stream and a
  per-(seed, tick, site) generator (verified by `scripts/crn_check.py`); disruption counted as UEs displaced
  by fixes. Re-run with seeds 11-13 in parallel.
- **E4 result:** LLM-written fixes (A3/A4) leave gNBs non-compliant longer than no agent (52 vs 40 site-h);
  A7 (SMT repair) lowest LLM-arm non-compliance (25 site-h) and 72% fewer users displaced than A5.
- Repository: all work committed as MuskanKumari2906 and pushed to MuskanKumari2906/agentic-ai-o-ran.
