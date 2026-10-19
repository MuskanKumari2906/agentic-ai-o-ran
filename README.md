# SecTwin: verifier-grounded Reflection Agent for O-RAN security compliance

Pinnacle Research Project P32 (Agentic AI for O-RAN in 6G), SSN College of Engineering.

SecTwin implements and evaluates the proposal *"Reflection Agent for Agentic AI-Based Security
Compliance in O-RAN"*. It has four parts:

1. **Compliance agents.** An LLM Assessor with retrieval over 3GPP / O-RAN / operator clauses, and a
   two-stage Reflection Agent: deterministic checks C1-C5 first, then an LLM critic. Seven
   experimental arms (A0-A6) plus two extensions: A7 (SMT minimal repair) and A5x (cross-family critic).
2. **Network digital twin.** A configurable 5G/O-RAN network (gNB sites, UEs, mobility, traffic) in which
   every gNB runs a full OAI-style configuration file. AS security algorithms are negotiated from that
   file at every attach and handover, so a misconfiguration has measurable consequences: null ciphering,
   spoofable RRC, attach failures, intercepted traffic. Attackers, config drift and the SMO compliance
   loop run inside it.
3. **RL remediation scheduler.** A PPO policy that decides *when* to push each verified fix, trading
   exposure against service disruption.
4. **NOC dashboard.** Live topology, assurance telemetry, an agent console that shows every reflection
   step, experiment results and a hash-chained audit trail.

Everything runs locally: Qwen2.5-7B-Instruct and Llama-3.1-8B through Ollama, nomic-embed-text for
retrieval, on a single RTX 4060 (8 GB).

## Quick start

```bash
# 1. LLM runtime (local)
bash scripts/serve_ollama.sh            # or start the Ollama app
ollama pull qwen2.5:7b-instruct && ollama pull llama3.1:8b && ollama pull nomic-embed-text

# 2. Python deps (Python 3.11+)
pip install fastapi uvicorn httpx pydantic rapidfuzz rank-bm25 z3-solver numpy pandas pyarrow gymnasium stable-baselines3

# 3. Dashboard (build once)
cd ui && npm install && npm run build && cd ..

# 4. Run
python -m uvicorn sectwin.api.server:app --port 8600
# open http://localhost:8600
```

Reproduce the study:

```bash
python -m sectwin.dataset.generate                  # 62 labelled configs -> data/
bash scripts/run_shard.sh 0/2 & bash scripts/run_shard.sh 1/2 &   # E1-E3 (LLM, resumable)
python -m sectwin.eval.twin_experiments e5          # cost of security features
python -m sectwin.rl.train 400000                   # E6 RL scheduler
python -m sectwin.eval.twin_experiments e4 6        # closed loop per arm (needs E1)
python -m sectwin.eval.analyze                      # results/summary.json
```

## Repository map

| Path | Content |
|---|---|
| `sectwin/conf/` | libconfig parser, OAI-style template, security view, **oracle policy** (ground truth), patcher |
| `sectwin/kb/clauses.py` | clause knowledge base with SHA-256 provenance manifest |
| `sectwin/dataset/` | seeded dataset generator (clean, vendor default, single, multi, decoy, context, noise) |
| `sectwin/retrieval/` | hybrid BM25 + dense retrieval, reciprocal-rank fusion |
| `sectwin/agents/` | Ollama client and cache, prompts, A0 scanner, verifier C1-C5, arm pipeline |
| `sectwin/repair/smt.py` | clause compiler + z3 minimal repair |
| `sectwin/twin/` | radio, traffic, engine (security, attacks, drift, telemetry), SMO service and policies |
| `sectwin/rl/` | remediation-scheduling environment, PPO training, in-twin policy |
| `sectwin/eval/` | metrics, metamorphic and poisoning variants, experiment runner, twin experiments, analysis |
| `sectwin/api/` | FastAPI backend, hash-chained audit log |
| `ui/` | React + TypeScript dashboard |
| `docs/` | `DESIGN.md`, `BUILD_LOG.md`, `RESULTS.md` |

## What is real and what is not

* **Real:** every LLM call (local models), the verifier, retrieval, SMT repair, RL training, all metrics.
  Each number in `results/` is computed from logged runs.
* **Synthetic or simulated:** the dataset (oracle-labelled mutations of an OAI-style template); the
  `interface_security` block (a project extension, not in OAI); the Operator Security Baseline (OSB);
  the network (a simulator, not OAI or ns-3); the remediation environment's severity weights.
* **Unverified:** 3GPP TS 33.501 and O-RAN WG11 clause texts are paraphrases and must be replaced by the
  official sentences before publication.
* **Pilot scale:** 45 test configurations, 1-2 repeats per arm. Confidence intervals are reported, and
  differences whose interval includes zero are called unresolved.
