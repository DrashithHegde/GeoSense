"""Hybrid retrieval over GeoSense's knowledge: curated notes + passages from source documents.

Items searched
  * 51 curated, cited knowledge notes (knowledge_base.jsonl) — short summaries the rules use.
  * Passages from authoritative documents (CPCB, WHO, NCAP, BMC, NDMA, papers…), ingested by
    scripts/ingest_corpus.py: ~180-word chunks with page numbers, so citations say "p. N".

Two rankers, fused with Reciprocal Rank Fusion (Cormack, Clarke & Büttcher, SIGIR 2009):
  1. BM25 keyword ranking (exact terms: "NDCI", "PM10", place names)
  2. Dense embeddings (bge-small-en-v1.5 via FastEmbed, or spaCy vectors as fallback), searched in
     pgvector (HNSW index, cosine) when the database has it, else in memory.
At most 2 passages per document are returned, so one long report cannot crowd out the rest.
Everything degrades gracefully: no corpus -> notes only; no embedding model -> BM25 only.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

KB_PATH = Path(__file__).parent / "knowledge_base.jsonl"
_TOKEN = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*")
_STOP = set("a an and are as at be by for from has have in is it its of on or that the this to was were with which "
            "not no than then there these those their can into over per also only more most".split())
RRF_K = 60
MAX_PER_DOC = 2


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1]


class BM25:
    def __init__(self, docs: list[dict], k1: float = 1.4, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf = []
        for d in docs:
            # title + tags weighted x2 (curated keywords / document titles)
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
            if line.strip():
                d = json.loads(line)
                d.setdefault("kind", "note")
                docs.append(d)
    return tuple(docs)


def _passage_item(p: dict) -> dict:
    page = p.get("page")
    return {"knowledge_id": p["id"], "kind": "passage", "doc_id": p["doc_id"], "page": page,
            "title": f"{p['title']}, p. {page}" if page else p["title"], "content": p["text"],
            "source": p["citation"] + (f", p. {page}" if page else ""), "url": p.get("url"),
            "source_type": p.get("source_type"), "supports": p.get("supports", []), "tags": "", "city": None}


@lru_cache(maxsize=1)
def load_items() -> tuple[dict, ...]:
    """Notes + document passages (if the corpus has been ingested)."""
    from app.services.rag.corpus import load_passages
    return tuple(list(load_kb()) + [_passage_item(p) for p in load_passages()])


@lru_cache(maxsize=1)
def _index() -> BM25:
    return BM25(list(load_items()))


@lru_cache(maxsize=1)
def _by_id() -> dict[str, dict]:
    return {d["knowledge_id"]: d for d in load_items()}


# ── embeddings ──────────────────────────────────────────────────────────────

def _embedder():
    from app.services.rag.embedder import get_embedder
    return get_embedder()


def embeddings_available() -> bool:
    return _embedder() is not None


@lru_cache(maxsize=1)
def _store():
    e = _embedder()
    if e is None:
        return None
    from app.services.rag.vector_store import get_store
    return get_store(e.name)


@lru_cache(maxsize=1)
def _note_matrix():
    """Fallback when no vector store has been built: embed the notes in memory."""
    import numpy as np
    e = _embedder()
    notes = list(load_kb())
    return [d["knowledge_id"] for d in notes], (e.embed_docs([f"{d['title']}. {d.get('tags', '')}. {d['content']}"
                                                              for d in notes]) if notes else np.zeros((0, 1)))


def _vector_scores(query: str, k: int = 60) -> dict[str, float]:
    e = _embedder()
    if e is None:
        return {}
    q = e.embed_query(query)
    st = _store()
    if st is not None:
        try:
            return st.search(q, k)
        except Exception:   # store unreachable / dropped: never fail the request — use the notes in memory
            getattr(_store, "cache_clear", lambda: None)()
            from app.services.rag.vector_store import MemoryStore
            mem = MemoryStore()
            if mem.ids:
                return mem.search(q, k)
    ids, m = _note_matrix()
    sims = m @ q
    return {ids[i]: float(sims[i]) for i in range(len(ids))}


def retrieval_mode() -> str:
    e = _embedder()
    n_pass = sum(1 for d in load_items() if d["kind"] == "passage")
    docs = len({d["doc_id"] for d in load_items() if d["kind"] == "passage"})
    corpus = f"{len(load_kb())} notes" + (f" + {n_pass} passages from {docs} documents" if n_pass else "")
    if e is None:
        return f"BM25 keyword only over {corpus}"
    st = _store()
    where = st.kind if st is not None else "in memory (notes only; corpus not ingested yet)"
    return f"hybrid BM25 + {e.name} embeddings ({where}), fused with RRF, over {corpus}"


def _ranks(scores: dict[str, float]) -> dict[str, int]:
    return {kid: i + 1 for i, kid in enumerate(sorted(scores, key=scores.get, reverse=True))}


def retrieve(query: str, k: int = 6, city: str | None = None, must_include: list[str] | None = None,
             min_score: float = 0.5, mode: str = "auto", include_passages: bool = True,
             include_notes: bool = True, strict: bool = False) -> list[dict[str, Any]]:
    """Top-k knowledge items. mode: "auto" | "hybrid" | "bm25" | "embed" (the last three for the evaluation).
    strict=True keeps only items that match on keywords AND meaning (used for evidence shown to users)."""
    items = [d for d in load_items() if (include_passages or d["kind"] == "note") and (include_notes or d["kind"] != "note")]
    allowed = {d["knowledge_id"] for d in items}
    bm_list = _index().score(tokenize(query))
    bm = {d["knowledge_id"]: s for d, s in zip(load_items(), bm_list) if d["knowledge_id"] in allowed and s > 0}
    use_emb = mode in ("auto", "hybrid", "embed") and embeddings_available()
    if mode == "embed" and not use_emb:
        return []
    cos = {kid: c for kid, c in _vector_scores(query).items() if kid in allowed} if use_emb else {}
    min_cos = _embedder().min_cos if use_emb else 1.0

    if mode == "bm25" or not use_emb:
        fused = {kid: s for kid, s in bm.items() if s >= min_score}
    elif mode == "embed":
        fused = {kid: c for kid, c in cos.items() if c >= min_cos}
    else:
        rb, rc = _ranks(bm), _ranks(cos)
        kw = {kid for kid, s in bm.items() if s >= min_score}
        sem = {kid for kid, c in cos.items() if c >= min_cos}
        # strict (used for evidence shown to the user): must match on keywords AND meaning
        cand = (kw & sem) if strict else (kw | sem)
        fused = {kid: (1.0 / (RRF_K + rb[kid]) if kid in rb else 0.0) + (1.0 / (RRF_K + rc[kid]) if kid in rc else 0.0)
                 for kid in cand}

    by_id = _by_id()
    ranked = []
    for kid, s in fused.items():
        doc = by_id[kid]
        dcity = doc.get("city")
        if dcity and city and dcity.lower() != city.lower() and not (city == "Thane" and dcity == "Mumbai"):
            s *= 0.6  # other-city context only if very relevant
        ranked.append((s, doc))
    ranked.sort(key=lambda x: x[0], reverse=True)
    chosen, per_doc = [], Counter()
    for s, d in ranked:
        if d["kind"] == "passage":
            if per_doc[d["doc_id"]] >= MAX_PER_DOC:
                continue
            per_doc[d["doc_id"]] += 1
        chosen.append((s, d))
        if len(chosen) >= k:
            break
    ids = {d["knowledge_id"] for _, d in chosen}
    for kid in must_include or []:
        if kid not in ids and kid in by_id:
            chosen.append((0.0, by_id[kid]))
            ids.add(kid)
    return [{**d, "score": round(float(s), 4)} for s, d in chosen]


def get(knowledge_id: str) -> dict | None:
    return _by_id().get(knowledge_id)


def corpus_stats() -> dict[str, Any]:
    from app.services.rag.vector_store import META
    items = load_items()
    meta = json.loads(META.read_text()) if META.exists() else None
    return {"notes": sum(1 for d in items if d["kind"] == "note"),
            "passages": sum(1 for d in items if d["kind"] == "passage"),
            "documents": len({d["doc_id"] for d in items if d["kind"] == "passage"}),
            "store": meta}
