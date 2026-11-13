"""Retrieval quality check for the GeoSense knowledge (notes + document passages).

49 labelled questions (app/services/rag/eval_questions.jsonl), each with the curated note(s) that
answer it. A retrieved item counts as correct if it is one of those notes, or a passage from a
source document that supports one of them (corpus_sources.json "supports").

Reported per retrieval mode (bm25 / embed / hybrid) and per corpus (notes only / notes + documents):
  Recall@5 — share of questions with a correct item in the top 5
  MRR      — mean reciprocal rank of the first correct item (1.0 = always first)
Writes data/rag/retrieval_eval.json.

    python scripts/eval_rag.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT))

from app.services.rag import retriever  # noqa: E402

QUESTIONS = SERVER_ROOT / "app" / "services" / "rag" / "eval_questions.jsonl"
OUT = SERVER_ROOT / "data" / "rag" / "retrieval_eval.json"


def _correct(item: dict, gold: list[str]) -> bool:
    return item["knowledge_id"] in gold or any(g in (item.get("supports") or []) for g in gold)


def evaluate(mode: str, k: int = 5, include_passages: bool = False) -> dict:
    qs = [json.loads(l) for l in QUESTIONS.read_text(encoding="utf-8").splitlines() if l.strip()]
    hits, rr, misses, passage_hits = 0, 0.0, [], 0
    for q in qs:
        got = retriever.retrieve(q["q"], k=k, mode=mode, min_score=0.0, include_passages=include_passages)
        rank = next((i + 1 for i, d in enumerate(got) if _correct(d, q["gold"])), None)
        if rank:
            hits += 1
            rr += 1.0 / rank
            passage_hits += int(got[rank - 1]["kind"] == "passage")
        else:
            misses.append({"question": q["q"], "expected": q["gold"], "got": [d["knowledge_id"] for d in got[:3]]})
    n = len(qs)
    return {"mode": mode, "corpus": "notes + documents" if include_passages else "notes only", "questions": n,
            "recall_at_5": round(hits / n, 3), "mrr": round(rr / n, 3),
            "first_hit_is_document_passage": passage_hits, "misses": misses}


def main() -> int:
    modes = ["bm25"] + (["embed", "hybrid"] if retriever.embeddings_available() else [])
    stats = retriever.corpus_stats()
    corpora = [False] + ([True] if stats["passages"] else [])
    results = {f"{m}{'+docs' if p else ''}": evaluate(m, include_passages=p) for p in corpora for m in modes}
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "retrieval_mode": retriever.retrieval_mode(),
              "knowledge_notes": stats["notes"], "document_passages": stats["passages"],
              "documents": stats["documents"], "store": stats["store"], "results": results}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(report["retrieval_mode"])
    for name, r in results.items():
        print(f"{name:12s} Recall@5 {r['recall_at_5']:.0%}   MRR {r['mrr']:.2f}   ({r['questions']} questions, "
              f"{r['corpus']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
