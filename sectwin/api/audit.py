"""Append-only, hash-chained audit log (tamper evident).

entry_hash = SHA-256(prev_hash || canonical JSON of the record). Changing or deleting any
earlier record breaks every later hash, which ``verify`` detects and localises.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path

GENESIS = "0" * 64


class AuditLog:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def _last_hash(self) -> str:
        if not self.path.exists():
            return GENESIS
        last = GENESIS
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last = json.loads(line)["entry_hash"]
        return last

    def append(self, kind: str, record: dict) -> dict:
        with self.lock:
            prev = self._last_hash()
            body = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": kind, "record": record}
            canon = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
            h = hashlib.sha256((prev + canon).encode()).hexdigest()
            entry = {**body, "prev_hash": prev, "entry_hash": h}
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
            return entry

    def entries(self, limit: int = 500) -> list[dict]:
        if not self.path.exists():
            return []
        lines = [l for l in self.path.read_text(encoding="utf-8").splitlines() if l.strip()]
        return [json.loads(l) for l in lines[-limit:]]

    def verify(self) -> dict:
        prev = GENESIS
        n = 0
        if not self.path.exists():
            return {"ok": True, "entries": 0}
        with open(self.path, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if not line.strip():
                    continue
                e = json.loads(line)
                body = {k: e[k] for k in ("ts", "kind", "record")}
                canon = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
                h = hashlib.sha256((prev + canon).encode()).hexdigest()
                if e["prev_hash"] != prev or e["entry_hash"] != h:
                    return {"ok": False, "entries": n, "broken_at": i, "ts": e.get("ts")}
                prev = h
                n += 1
        return {"ok": True, "entries": n, "head": prev}
