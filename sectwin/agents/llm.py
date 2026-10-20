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

    from .backend import provider_for
    provider = provider_for(model)
    last_err = None
    for attempt in range(retries):
        try:
            t0 = time.time()
            if provider == "anthropic":
                content, pt, ot = _chat_anthropic(messages, model, schema, num_predict)
            elif provider == "openai":
                content, pt, ot = _chat_openai(messages, model, schema, temperature, seed, num_predict, timeout)
            else:
                r = httpx.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=timeout)
                r.raise_for_status()
                j = r.json()
                content, pt, ot = j["message"]["content"], j.get("prompt_eval_count", 0), j.get("eval_count", 0)
            dt = time.time() - t0
            res = LLMResult(content, _parse(content), model, pt, ot, dt, False)
            if use_cache:
                cpath.parent.mkdir(parents=True, exist_ok=True)
                cpath.write_text(json.dumps({"content": content, "prompt_tokens": res.prompt_tokens,
                                             "output_tokens": res.output_tokens, "seconds": dt}),
                                 encoding="utf-8")
            return res
        except PermanentError as e:     # bad request / auth / refusal: retrying will not help
            return LLMResult("", None, model, 0, 0, 0.0, False, error=str(e))
        except Exception as e:  # server restarting, model loading, rate limits, timeouts: back off and retry
            last_err = f"{type(e).__name__}: {e}"
            time.sleep(min(60, 5 * (2 ** attempt)))
    return LLMResult("", None, model, 0, 0, 0.0, False, error=last_err)


class PermanentError(Exception):
    pass


def _split_system(messages):
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    rest = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]
    return system, rest


_ANTHROPIC = {"client": None, "use_format": True}
JSON_ONLY = "\n\nRespond with one JSON object that matches this JSON schema, and nothing else:\n"


def _chat_anthropic(messages, model, schema, num_predict):
    """Claude via the official Anthropic SDK: JSON-schema structured output, server-side refusal fallback."""
    import anthropic
    if _ANTHROPIC["client"] is None:
        _ANTHROPIC["client"] = anthropic.Anthropic(max_retries=3)
    client = _ANTHROPIC["client"]
    system, rest = _split_system(messages)
    kwargs = dict(model=model, max_tokens=max(16000, num_predict), system=system, messages=rest,
                  betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    if schema is not None and _ANTHROPIC["use_format"]:
        kwargs["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
    elif schema is not None:
        kwargs["system"] = system + JSON_ONLY + json.dumps(schema)
    try:
        resp = client.beta.messages.create(**kwargs)
    except anthropic.BadRequestError as e:
        if "output_config" in kwargs:          # schema features not accepted: fall back to prompt-only JSON
            _ANTHROPIC["use_format"] = False
            kwargs.pop("output_config")
            kwargs["system"] = system + JSON_ONLY + json.dumps(schema)
            resp = client.beta.messages.create(**kwargs)
        else:
            raise PermanentError(f"BadRequestError: {e}") from e
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.NotFoundError) as e:
        raise PermanentError(f"{type(e).__name__}: {e}") from e
    if resp.stop_reason == "refusal":
        raise PermanentError(f"refusal: {getattr(resp, 'stop_details', None)}")
    text = "".join(b.text for b in resp.content if b.type == "text")
    return text, resp.usage.input_tokens, resp.usage.output_tokens


def _chat_openai(messages, model, schema, temperature, seed, num_predict, timeout):
    """Any OpenAI-compatible chat endpoint (OPENAI_BASE_URL, default api.openai.com)."""
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    msgs = [dict(m) for m in messages]
    if schema is not None and msgs and msgs[0]["role"] == "system":
        msgs[0] = {"role": "system", "content": msgs[0]["content"] + JSON_ONLY + json.dumps(schema)}
    body = {"model": model, "messages": msgs, "temperature": temperature, "max_tokens": num_predict, "seed": seed}
    if schema is not None:
        body["response_format"] = {"type": "json_object"}
    r = httpx.post(f"{base}/chat/completions", json=body, timeout=timeout,
                   headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"})
    if r.status_code in (400, 401, 403, 404):
        raise PermanentError(f"HTTP {r.status_code}: {r.text[:300]}")
    r.raise_for_status()
    j = r.json()
    u = j.get("usage") or {}
    return j["choices"][0]["message"]["content"], u.get("prompt_tokens", 0), u.get("completion_tokens", 0)


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
