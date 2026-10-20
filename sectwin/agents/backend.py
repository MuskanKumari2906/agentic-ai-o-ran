"""Choose where the LLM runs, in this order:

1. ``ollama-gpu``  Ollama is running, an NVIDIA GPU with >= 6 GB is present and qwen2.5:7b-instruct is pulled.
2. ``anthropic``   ANTHROPIC_API_KEY is set (model: SECTWIN_API_MODEL or claude-opus-5-5).
   ``openai``      or OPENAI_API_KEY + SECTWIN_API_MODEL are set (any OpenAI-compatible endpoint via
                   OPENAI_BASE_URL, e.g. Groq, Gemini, OpenRouter, OpenAI).
3. ``ollama-cpu``  Ollama is running without a usable GPU: smallest pulled Qwen model (qwen2.5:3b-instruct
                   recommended); expect minutes per assessment.
4. ``replay``      nothing available: the dashboard replays the recorded experiment runs. Everything except
                   "Run live" works.

Override with SECTWIN_BACKEND=ollama-gpu|anthropic|openai|ollama-cpu|replay.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time

_cache: dict = {"t": 0.0, "value": None}

GPU_MODEL = "qwen2.5:7b-instruct"
GPU_CRITIC = "llama3.1:8b"
CPU_MODELS = ["qwen2.5:3b-instruct", "qwen2.5:1.5b-instruct", "qwen2.5:7b-instruct"]
EMBED_MODEL = "nomic-embed-text"
DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"


def gpu_vram_mb() -> int:
    """Total VRAM of the first NVIDIA GPU in MiB, 0 if none."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return 0
    try:
        out = subprocess.run([exe, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout
        return int(out.strip().splitlines()[0])
    except Exception:
        return 0


def _ollama_models() -> list[str]:
    from .llm import available_models
    return available_models()


def _has(models: list[str], name: str) -> bool:
    base = name.split(":")[0]
    tag = name.split(":")[1] if ":" in name else "latest"
    return any(m == name or (m.split(":")[0] == base and m.split(":")[-1] == tag) for m in models)


def resolve(force_refresh: bool = False) -> dict:
    if not force_refresh and _cache["value"] and time.time() - _cache["t"] < 60:
        return _cache["value"]
    forced = os.environ.get("SECTWIN_BACKEND", "").strip().lower()
    models = _ollama_models()
    vram = gpu_vram_mb()
    embed = _has(models, EMBED_MODEL)
    api_model = os.environ.get("SECTWIN_API_MODEL", "").strip()

    def ollama_gpu():
        if models and vram >= 6000 and _has(models, GPU_MODEL):
            critic = GPU_CRITIC if _has(models, GPU_CRITIC) else GPU_MODEL
            return {"kind": "ollama-gpu", "model": GPU_MODEL, "critic": critic, "embeddings": embed,
                    "label": f"{GPU_MODEL} on GPU ({round(vram / 1024)} GB)"}

    def anthropic():
        if os.environ.get("ANTHROPIC_API_KEY"):
            m = api_model or DEFAULT_ANTHROPIC_MODEL
            return {"kind": "anthropic", "model": m, "critic": m, "embeddings": embed, "label": f"{m} (API)"}

    def openai():
        if os.environ.get("OPENAI_API_KEY") and api_model:
            return {"kind": "openai", "model": api_model, "critic": api_model, "embeddings": embed,
                    "label": f"{api_model} (API)"}

    def ollama_cpu():
        if models:
            for m in CPU_MODELS:
                if _has(models, m):
                    return {"kind": "ollama-cpu", "model": m, "critic": m, "embeddings": embed,
                            "label": f"{m} on CPU (slow)"}

    replay = {"kind": "replay", "model": None, "critic": None, "embeddings": embed,
              "label": "Replay mode (no LLM)"}
    order = {"ollama-gpu": [ollama_gpu], "anthropic": [anthropic], "openai": [openai], "ollama-cpu": [ollama_cpu],
             "replay": []}.get(forced, [ollama_gpu, anthropic, openai, ollama_cpu])
    value = next((v for f in order if (v := f())), replay)
    value["gpu_vram_mb"] = vram
    _cache.update(t=time.time(), value=value)
    return value


def provider_for(model: str) -> str:
    """Which client serves a given model name."""
    if model.startswith("claude"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY") and model == os.environ.get("SECTWIN_API_MODEL", ""):
        return "openai"
    return "ollama"
