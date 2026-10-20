# Installing SecTwin on a laptop

**Short version:** the demo needs only Python. No GPU, no AI model and no internet are needed once it is
installed. Everything the experiments measured is stored in the repository and is replayed by the dashboard.

## 1. What you need

| | Needed for the demo? | Notes |
|---|---|---|
| Windows 10/11, macOS or Linux, 8 GB RAM | yes | any normal laptop |
| Python 3.11 or newer | yes | https://www.python.org/downloads/ (on Windows tick **"Add python.exe to PATH"**) |
| Git | to download the project | https://git-scm.com/downloads, or use GitHub's **Code -> Download ZIP** |
| GPU | **no** | only speeds up live AI assessments |
| Ollama or an API key | **no** | only for the "Run live" button (section 4) |
| Node.js | no | the dashboard is already built (`ui/dist`) |

## 2. Install (once, about 5 minutes)

**Windows**

1. Download the project: `git clone https://github.com/MuskanKumari2906/agentic-ai-o-ran.git`
   (or Download ZIP from GitHub and extract it).
2. Open the folder and double-click **`setup.bat`**. It creates a private Python environment (`.venv`)
   and installs the packages. Wait for "Setup finished".

**macOS / Linux**

```bash
git clone https://github.com/MuskanKumari2906/agentic-ai-o-ran.git
cd agentic-ai-o-ran
bash run_demo.sh      # first run installs, later runs just start
```

## 3. Start the demo

* Windows: double-click **`run_demo.bat`**. A black window opens (leave it open) and the browser opens
  http://localhost:8600. If the page is blank, wait five seconds and refresh.
* macOS / Linux: `bash run_demo.sh`.
* To stop: close the black window (or press Ctrl+C in it).

The top-right of the dashboard shows which AI backend is active. On a laptop without a GPU and without a
key it says **"Replay mode (no LLM)"**. That is normal: every page works, and recorded runs are shown.

## 4. Optional: live AI assessments

The dashboard picks a backend automatically, in this order:

| Order | Backend | When it is used | Speed per assessment |
|---|---|---|---|
| 1 | Local model on GPU | Ollama running, NVIDIA GPU with 6 GB or more, `qwen2.5:7b-instruct` pulled | 30 s to 3 min |
| 2 | Cloud API | `ANTHROPIC_API_KEY` set (or `OPENAI_API_KEY` + `SECTWIN_API_MODEL` for any OpenAI-compatible service) | 20 s to 2 min, costs a few cents |
| 3 | Local model on CPU | Ollama running without a usable GPU | 3 to 15 min, lower quality with small models |
| 4 | Replay | none of the above | instant (recorded runs) |

**Cloud API (best choice without a GPU).** In the black window's folder, on Windows:

```bat
set ANTHROPIC_API_KEY=your-key-here
run_demo.bat
```

Optional: `set SECTWIN_API_MODEL=<model id>` to pick a different Claude model. For an OpenAI-compatible
service (Groq, Gemini, OpenRouter, OpenAI) set `OPENAI_API_KEY`, `OPENAI_BASE_URL` and `SECTWIN_API_MODEL`.
Never put keys in files that are committed to Git.

**Local model on CPU.** Install Ollama (https://ollama.com/download), then:

```bash
ollama pull qwen2.5:3b-instruct
ollama pull nomic-embed-text
```

Restart `run_demo.bat`. Expect several minutes per live assessment; the 3B model is weaker than the 7B
model used in the experiments.

**Force a backend:** `set SECTWIN_BACKEND=replay` (or `ollama-gpu`, `anthropic`, `openai`, `ollama-cpu`).

## 5. Optional: re-running the research

Only needed to reproduce the experiments, not for the demo.

```bash
pip install -r requirements-research.txt   # adds PyTorch, RL and plotting libraries (large)
```

Then follow "Reproduce the study" in the README. The full E1-E3 run took about 10 hours on an RTX 4060.
The ns-3 5G-LENA cross-check was run once in WSL Ubuntu (`scripts/ns3/`); its results are in
`results/ns3_validation.json` and it is not needed for the demo.

## 6. Troubleshooting

| Problem | Fix |
|---|---|
| `python` is not recognised | reinstall Python with "Add python.exe to PATH" ticked, then run `setup.bat` again |
| Browser says "can't reach this page" | the black window must stay open; wait a few seconds and refresh |
| Port 8600 already in use | close the other window running the demo, or restart the laptop |
| "Run live" shows "No LLM backend is available" | expected in replay mode; see section 4 |
| Map moves slowly | in the scenario panel choose 7 sites and 500 UEs |
