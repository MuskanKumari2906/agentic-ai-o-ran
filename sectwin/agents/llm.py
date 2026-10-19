"""Ollama chat client with structured output, token accounting and an on-disk cache.

The cache makes overnight experiment runs resumable: a crashed or interrupted run
re-uses every completed LLM call (keyed by model, messages, schema and options).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
PRIMARY_MODEL = os.environ.get("SECTWIN_MODEL", "qwen2.5:7b-instruct")
SECOND_MODEL = os.environ.get("SECTWIN_MODEL2", "llama3.1:8b")
CACHE_DIR = Path(__file__).resolve().parents[2] / "runs" / "llm_cache"


@dataclass
class LLMResult:
    content: str
    data: dict | None
    model: str
    prompt_tokens: int
    output_tokens: int
    seconds: float
    cached: bool
    error: str | None = None


@dataclass
class CallLog:
    calls: list = field(default_factory=list)

    def add(self, role: str, r: LLMResult):
        self.calls.append({"role": role, "model": r.model, "prompt_tokens": r.prompt_tokens,
                           "output_tokens": r.output_tokens, "seconds": round(r.seconds, 2),
                           "cached": r.cached, "error": r.error})

    @property
    def tokens(self):
        return sum(c["prompt_tokens"] + c["output_tokens"] for c in self.calls)

    @property
    def seconds(self):
        return sum(c["seconds"] for c in self.calls)


def _key(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def chat(messages: list[dict], *, model: str = PRIMARY_MODEL, schema: dict | None = None,
         temperature: float = 0.2, seed: int = 0, num_ctx: int = 8192, num_predict: int = 1200,
         use_cache: bool = True, retries: int = 6, timeout: float = 600) -> LLMResult:
    options = {"temperature": temperature, "seed": seed, "num_ctx": num_ctx, "num_predict": num_predict}
    payload = {"model": model, "messages": messages, "stream": False, "options": options,
               "keep_alive": "30m"}
    if schema is not None:
        payload["format"] = schema
    key = _key(payload)
    cpath = CACHE_DIR / key[:2] / f"{key}.json"
    if use_cache and cpath.exists():
        c = json.loads(cpath.read_text(encoding="utf-8"))
        return LLMResult(c["content"], _parse(c["content"]), model, c["prompt_tokens"],
                         c["output_tokens"], c["seconds"], True)

    last_err = None
    for attempt in range(retries):
        try:
            t0 = time.time()
            r = httpx.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=timeout)
            r.raise_for_status()
            j = r.json()
            dt = time.time() - t0
            content = j["message"]["content"]
            res = LLMResult(content, _parse(content), model, j.get("prompt_eval_count", 0),
                            j.get("eval_count", 0), dt, False)
            if use_cache:
                cpath.parent.mkdir(parents=True, exist_ok=True)
                cpath.write_text(json.dumps({"content": content, "prompt_tokens": res.prompt_tokens,
                                             "output_tokens": res.output_tokens, "seconds": dt}),
                                 encoding="utf-8")
            return res
        except Exception as e:  # server restarting, model loading, timeouts: back off and retry
            last_err = f"{type(e).__name__}: {e}"
            time.sleep(min(60, 5 * (2 ** attempt)))
    return LLMResult("", None, model, 0, 0, 0.0, False, error=last_err)


def _parse(content: str) -> dict | None:
    try:
        return json.loads(content)
    except Exception:
        s, e = content.find("{"), content.rfind("}")
        if s >= 0 and e > s:
            try:
                return json.loads(content[s:e + 1])
            except Exception:
                return None
        return None


def available_models() -> list[str]:
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []
