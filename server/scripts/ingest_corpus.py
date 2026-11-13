"""RAG ingestion pipeline: documents -> passages -> embeddings -> pgvector.

    python scripts/ingest_corpus.py            # download (cached), extract, chunk, embed, store
    python scripts/ingest_corpus.py --embed-only   # re-embed existing passages (e.g. new model)

Steps
  1. Download each document in app/services/rag/corpus_sources.json (first working mirror; cached
     in data/rag/corpus/raw with its SHA-256).
  2. Extract text page by page (pypdf), clean it (hyphenation, reference lists, contents pages).
  3. Chunk into ~180-word passages with 40-word overlap, never across pages (citable "p. N").
  4. Embed the passages AND the 51 curated notes with the RAG embedding model.
  5. Store in pgvector (HNSW cosine index) — or in memory if the database has no pgvector.
Then run scripts/eval_rag.py to measure retrieval quality.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
for p in (str(SERVER_ROOT.parent), str(SERVER_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--embed-only", action="store_true")
    a = ap.parse_args()

    from app.services.rag import retriever
    from app.services.rag.corpus import build_passages, load_passages
    from app.services.rag.embedder import get_embedder
    from app.services.rag.vector_store import build_store

    if a.embed_only:
        passages, report = load_passages(), None
    else:
        print("1-3. Download, extract and chunk documents")
        passages, report = build_passages()
    emb = get_embedder(allow_download=True)   # downloads bge-small once (~130 MB) into data/rag/models
    if emb is None:
        print("No embedding model available (pip install fastembed, or spaCy en_core_web_md). Passages saved; "
              "retrieval will use BM25 until embeddings are built.")
        return 1
    notes = [{"id": d["knowledge_id"], "kind": "note", "title": d["title"], "text": d["content"], "tags": d.get("tags"),
              "citation": d["source"], "url": d.get("url"), "source_type": d.get("source_type")}
             for d in retriever.load_kb()]
    print(f"4-5. Embed + store ({len(notes)} notes, {len(passages)} passages)")
    meta = build_store(notes + passages, emb)
    ok = [r for r in (report or []) if r["status"] == "ok"]
    print(json.dumps({"documents_ingested": len(ok), "documents_failed": [r["id"] for r in (report or [])
                                                                            if r["status"] != "ok"],
                      **meta}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
