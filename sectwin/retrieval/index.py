"""Clause-aware hybrid retrieval: BM25 (keyword channel) + dense embeddings, fused with RRF.

Chunks are whole clauses, so every retrieved item carries a clause ID. That is what makes
the citation check (C3) possible. Extra (e.g. poisoned) chunks can be injected for E3.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from rank_bm25 import BM25Okapi

from ..kb.clauses import CLAUSES, Clause

EMBED_MODEL = "nomic-embed-text"        # served by the local Ollama runtime
QUERY_PREFIX = "search_query: "
DOC_PREFIX = "search_document: "


def _tok(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:\.[0-9]+)*", s.lower())


def embed(texts: list[str]) -> np.ndarray:
    import httpx
    from ..agents.llm import OLLAMA_URL
    r = httpx.post(f"{OLLAMA_URL}/api/embed", json={"model": EMBED_MODEL, "input": texts}, timeout=300)
    r.raise_for_status()
    e = np.array(r.json()["embeddings"], dtype=np.float32)
    return e / np.linalg.norm(e, axis=1, keepdims=True)


@lru_cache(maxsize=512)
def _embed_query(q: str) -> np.ndarray:
    return embed([QUERY_PREFIX + q])[0]


@dataclass
class Hit:
    clause: Clause
    score: float
    bm25_rank: int | None
    dense_rank: int | None


class ClauseIndex:
    def __init__(self, clauses: list[Clause] | None = None, use_dense: bool = True):
        self.clauses = list(clauses or CLAUSES)
        docs = [f"{c.clause_id} {c.title} {c.text}" for c in self.clauses]
        self.bm25 = BM25Okapi([_tok(d) for d in docs])
        self.use_dense = use_dense
        self.emb = None
        if use_dense:
            self.emb = embed([DOC_PREFIX + d for d in docs])

    def search(self, query: str, k: int = 5, rrf_k: int = 60) -> list[Hit]:
        n = len(self.clauses)
        bm = self.bm25.get_scores(_tok(query))
        bm_order = list(np.argsort(-bm))
        ranks_bm = {i: r for r, i in enumerate(bm_order)}
        ranks_de = {}
        if self.use_dense:
            q = _embed_query(query)
            de = self.emb @ q
            ranks_de = {i: r for r, i in enumerate(np.argsort(-de))}
        fused = []
        for i in range(n):
            s = 1.0 / (rrf_k + ranks_bm[i])
            if ranks_de:
                s += 1.0 / (rrf_k + ranks_de[i])
            fused.append(s)
        order = np.argsort(-np.array(fused))[:k]
        return [Hit(self.clauses[i], float(fused[i]), ranks_bm[i], ranks_de.get(i)) for i in order]

    def multi_search(self, queries: list[str], k_each: int = 4, k_total: int = 8) -> list[Hit]:
        best: dict[str, Hit] = {}
        for q in queries:
            for h in self.search(q, k_each):
                cur = best.get(h.clause.clause_id)
                if cur is None or h.score > cur.score:
                    best[h.clause.clause_id] = h
        return sorted(best.values(), key=lambda h: -h.score)[:k_total]
