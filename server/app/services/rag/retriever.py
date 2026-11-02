"""Hybrid retrieval over the curated, cited GeoSense knowledge base.

Two rankers, fused with Reciprocal Rank Fusion (Cormack et al., SIGIR 2009):
  1. BM25 keyword ranking (exact terms: "NDCI", "PM10", place names)
  2. Embedding ranking: cosine similarity of 300-d spaCy `en_core_web_md` word vectors
     (mean of content-word vectors), which matches meaning ("why is it so warm" ->
     heat notes) even without shared keywords.
Everything runs offline. If the embedding model is not installed, or
RAG_EMBEDDINGS=off, retrieval falls back to BM25 alone (same API).
"""
from __future__ import annotations

import json
import math
import os
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

KB_PATH = Path(__file__).parent / "knowledge_base.jsonl"
_TOKEN = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*")
_STOP = set("a an and are as at be by for from has have in is it its of on or that the this to was were with which "
            "not no than then there these those their can into over per also only more most".split())


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1]


class BM25:
    def __init__(self, docs: list[dict], k1: float = 1.4, b: float = 0.75):
        self.docs = docs
        self.k1, self.b = k1, b
        self.tf = []
        for d in docs:
            # title + tags weighted x2 (they are curated keywords)
            toks = tokenize(d["content"]) + 2 * tokenize(d["title"] + " " + d.get("tags", ""))
            self.tf.append(Counter(toks))
        self.dl = [sum(c.values()) for c in self.tf]
        self.avgdl = sum(self.dl) / max(1, len(self.dl))
        df = Counter(t for c in self.tf for t in c)
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def score(self, query_tokens: list[str]) -> list[float]:
        out = []
        for tf, dl in zip(self.tf, self.dl):
            s = 0.0
            for t in query_tokens:
                if t in tf:
                    f = tf[t]
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            out.append(s)
        return out


@lru_cache(maxsize=1)
def load_kb() -> tuple[dict, ...]:
    docs = []
    with KB_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                docs.append(json.loads(line))
    return tuple(docs)


@lru_cache(maxsize=1)
def _index() -> BM25:
    return BM25(list(load_kb()))


# ── embeddings ──────────────────────────────────────────────────────────────
EMBED_MODEL = "en_core_web_md"
RRF_K = 60
EMB_MIN_COS = 0.55   # embedding-only matches must be at least this similar


@lru_cache(maxsize=1)
def _nlp():
    if os.getenv("RAG_EMBEDDINGS", "on").lower() == "off":
        return None
    try:
        import spacy
        return spacy.load(EMBED_MODEL, exclude=["parser", "ner", "tagger", "lemmatizer",
                                                "attribute_ruler", "senter", "morphologizer"])
    except Exception:  # model not installed -> BM25 only
        return None


def _embed(text: str):
    import numpy as np
    nlp = _nlp()
    doc = nlp(text)
    vecs = [t.vector for t in doc if t.has_vector and not t.is_stop and not t.is_punct and not t.like_num]
    if not vecs:
        vecs = [doc.vector]
    v = np.mean(vecs, axis=0)
    n = float(np.linalg.norm(v))
    return v / n if n else v


@lru_cache(maxsize=1)
def _doc_matrix():
    import numpy as np
    return np.vstack([_embed(f"{d['title']}. {d.get('tags', '')}. {d['content']}") for d in load_kb()])


def embeddings_available() -> bool:
    return _nlp() is not None


def retrieval_mode() -> str:
    return "hybrid (BM25 + spaCy en_core_web_md embeddings, RRF)" if embeddings_available() else "BM25 keyword only"


def _ranks(scores: list[float]) -> list[int]:
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    r = [0] * len(scores)
    for pos, i in enumerate(order):
        r[i] = pos + 1
    return r


def retrieve(query: str, k: int = 6, city: str | None = None, must_include: list[str] | None = None,
             min_score: float = 0.5, mode: str = "auto") -> list[dict[str, Any]]:
    """Top-k knowledge passages (hybrid when embeddings are available).

    mode: "auto" (hybrid if possible) | "hybrid" | "bm25" | "embed" — the last three are used by the
    retrieval evaluation. City-specific docs for other cities are down-weighted.
    """
    kb = load_kb()
    bm = _index().score(tokenize(query))
    use_emb = mode in ("auto", "hybrid", "embed") and embeddings_available()
    if mode == "embed" and not use_emb:
        return []
    cos = list(_doc_matrix() @ _embed(query)) if use_emb else [0.0] * len(kb)

    if mode == "bm25" or not use_emb:
        fused = list(bm)
        relevant = [b >= min_score for b in bm]
    elif mode == "embed":
        fused = [float(c) for c in cos]
        relevant = [c >= EMB_MIN_COS for c in cos]
    else:
        rb, rc = _ranks(bm), _ranks(cos)
        fused = [1.0 / (RRF_K + rb[i]) + 1.0 / (RRF_K + rc[i]) for i in range(len(kb))]
        relevant = [bm[i] >= min_score or cos[i] >= EMB_MIN_COS for i in range(len(kb))]

    ranked = []
    for i, doc in enumerate(kb):
        if not relevant[i]:
            continue
        s = fused[i]
        dcity = doc.get("city")
        if dcity and city and dcity.lower() != city.lower() and not (city == "Thane" and dcity == "Mumbai"):
            s *= 0.6  # other-city context only if very relevant
        ranked.append((s, doc))
    ranked.sort(key=lambda x: x[0], reverse=True)
    chosen = ranked[:k]
    ids = {d["knowledge_id"] for _, d in chosen}
    for kid in must_include or []:
        if kid not in ids:
            doc = next((d for d in kb if d["knowledge_id"] == kid), None)
            if doc:
                chosen.append((0.0, doc))
                ids.add(kid)
    return [{**d, "score": round(float(s), 3)} for s, d in chosen]


def get(knowledge_id: str) -> dict | None:
    return next((d for d in load_kb() if d["knowledge_id"] == knowledge_id), None)
