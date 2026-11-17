"""Vector store for RAG: pgvector in the project's PostgreSQL (HNSW, cosine), or in-memory.

Both hold the same items — curated knowledge notes and document passages — with their
embedding. pgvector is used when the extension is available in the database (the project's
Docker image includes it); otherwise vectors are kept in data/rag/corpus/vectors.npy and searched
with an exact dot product (fine for a few thousand passages).
"""
from __future__ import annotations

import json
from typing import Any

import numpy as np
from sqlalchemy import text

from app.services.rag.corpus import CORPUS_DIR

VECTORS = CORPUS_DIR / "vectors.npy"
VECTOR_IDS = CORPUS_DIR / "vector_ids.json"
META = CORPUS_DIR / "store_meta.json"


def _vec_literal(v: np.ndarray) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v.tolist()) + "]"


class PgVectorStore:
    kind = "pgvector (HNSW, cosine)"

    def __init__(self, engine):
        self.engine = engine

    @staticmethod
    def try_enable(engine) -> bool:
        try:
            with engine.begin() as c:
                c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            return True
        except Exception:
            return False

    def ensure_schema(self, dim: int) -> None:
        with self.engine.begin() as c:
            # only ever look at / change the table in the CURRENT schema (never another schema's table)
            sch = c.execute(text("SELECT current_schema()")).scalar()
            row = c.execute(text("SELECT to_regclass(:t)"), {"t": f"{sch}.rag_items"}).scalar()
            if row:
                cur = c.execute(text("SELECT atttypmod FROM pg_attribute WHERE attrelid = CAST(:t AS regclass) "
                                     "AND attname = 'embedding'"), {"t": f"{sch}.rag_items"}).scalar()
                if cur is not None and int(cur) != dim:      # embedding model changed -> rebuild
                    c.execute(text(f'DROP TABLE "{sch}".rag_items'))
            c.execute(text(f"""
                CREATE TABLE IF NOT EXISTS rag_items (
                    id text PRIMARY KEY, kind text NOT NULL, doc_id text, page int,
                    title text, citation text, url text, source_type text,
                    text text NOT NULL, meta jsonb, embedding vector({dim}) NOT NULL)"""))
            c.execute(text("CREATE INDEX IF NOT EXISTS rag_items_hnsw ON rag_items "
                           "USING hnsw (embedding vector_cosine_ops)"))
            c.execute(text("CREATE TABLE IF NOT EXISTS rag_meta (key text PRIMARY KEY, value jsonb)"))

    def replace_all(self, items: list[dict], vectors: np.ndarray, meta: dict) -> int:
        with self.engine.begin() as c:
            c.execute(text("TRUNCATE rag_items"))
            rows = [{"id": it["id"], "kind": it["kind"], "doc_id": it.get("doc_id"), "page": it.get("page"),
                     "title": it.get("title"), "citation": it.get("citation"), "url": it.get("url"),
                     "source_type": it.get("source_type"), "text": it["text"],
                     "meta": json.dumps({k: it.get(k) for k in ("supports", "doi")}), "emb": _vec_literal(v)}
                    for it, v in zip(items, vectors)]
            for i in range(0, len(rows), 500):
                c.execute(text("""INSERT INTO rag_items (id, kind, doc_id, page, title, citation, url, source_type,
                                  text, meta, embedding)
                                  VALUES (:id, :kind, :doc_id, :page, :title, :citation, :url, :source_type, :text,
                                          CAST(:meta AS jsonb), CAST(:emb AS vector))"""), rows[i:i + 500])
            c.execute(text("INSERT INTO rag_meta (key, value) VALUES ('store', CAST(:m AS jsonb)) "
                           "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"), {"m": json.dumps(meta)})
        return len(rows)

    def meta(self) -> dict | None:
        """Store metadata, only if the vector table really exists and is filled."""
        try:
            with self.engine.connect() as c:
                if not c.execute(text("SELECT to_regclass('rag_items')")).scalar():
                    return None
                n = c.execute(text("SELECT count(*) FROM rag_items")).scalar()
                v = c.execute(text("SELECT value FROM rag_meta WHERE key = 'store'")).scalar()
            m = v if isinstance(v, dict) else (json.loads(v) if v else None)
            return m if m and n else None
        except Exception:
            return None

    def search(self, qvec: np.ndarray, k: int = 50) -> dict[str, float]:
        with self.engine.connect() as c:
            rows = c.execute(text("SELECT id, 1 - (embedding <=> CAST(:q AS vector)) AS cos FROM rag_items "
                                  "ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k"),
                             {"q": _vec_literal(qvec), "k": k}).all()
        return {r[0]: float(r[1]) for r in rows}


class MemoryStore:
    kind = "in-memory (exact cosine)"

    def __init__(self):
        self.ids: list[str] = json.loads(VECTOR_IDS.read_text()) if VECTOR_IDS.exists() else []
        self.vecs = np.load(VECTORS) if VECTORS.exists() else np.zeros((0, 1), dtype="float32")

    @staticmethod
    def save(items: list[dict], vectors: np.ndarray, meta: dict) -> int:
        CORPUS_DIR.mkdir(parents=True, exist_ok=True)
        np.save(VECTORS, vectors.astype("float32"))
        VECTOR_IDS.write_text(json.dumps([it["id"] for it in items]))
        META.write_text(json.dumps(meta, indent=1))
        return len(items)

    def meta(self) -> dict | None:
        return json.loads(META.read_text()) if META.exists() else None

    def search(self, qvec: np.ndarray, k: int = 50) -> dict[str, float]:
        if not self.ids:
            return {}
        sims = self.vecs @ qvec
        top = np.argsort(-sims)[:k]
        return {self.ids[i]: float(sims[i]) for i in top}


def build_store(items: list[dict], embedder, log=print) -> dict[str, Any]:
    """Embed every item (notes + passages) and write them to pgvector, or to disk if unavailable."""
    from app.database import engine

    log(f"  embedding {len(items)} items with {embedder.name} ({embedder.dim}-d) …")
    # same text recipe as the in-memory fallback: title + curated tags (notes) + text
    vecs = embedder.embed_docs([f"{it.get('title', '')}. {it.get('tags') or ''}. {it['text']}" for it in items])
    meta = {"embedder": embedder.name, "dim": int(vecs.shape[1]), "items": len(items),
            "notes": sum(1 for it in items if it["kind"] == "note"),
            "passages": sum(1 for it in items if it["kind"] == "passage")}
    MemoryStore.save(items, vecs, meta)          # always keep a portable copy
    if PgVectorStore.try_enable(engine):
        pg = PgVectorStore(engine)
        pg.ensure_schema(int(vecs.shape[1]))
        pg.replace_all(items, vecs, meta)
        meta["store"] = PgVectorStore.kind
    else:
        meta["store"] = MemoryStore.kind + " (pgvector extension not available in this database)"
    META.write_text(json.dumps(meta, indent=1))
    log(f"  stored in {meta['store']}")
    return meta


def get_store(embedder_name: str):
    """The store to query, only if it was built with the same embedding model."""
    try:
        from app.database import engine
        pg = PgVectorStore(engine)
        m = pg.meta()
        if m and m.get("embedder") == embedder_name and m.get("items"):
            return pg
    except Exception:
        pass
    mem = MemoryStore()
    m = mem.meta()
    if m and m.get("embedder") == embedder_name and mem.ids:
        return mem
    return None
