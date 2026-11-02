"""Retrieval quality check for the GeoSense knowledge base.

42 labelled questions (app/services/rag/eval_questions.jsonl), each with the
note(s) that should be found. Reports, per retrieval mode:
  Recall@5 — share of questions whose correct note is in the top 5
  MRR      — mean reciprocal rank of the first correct note (1.0 = always first)
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


def evaluate(mode: str, k: int = 5) -> dict:
    qs = [json.loads(l) for l in QUESTIONS.read_text(encoding="utf-8").splitlines() if l.strip()]
    hits, rr, misses = 0, 0.0, []
    for q in qs:
        ids = [d["knowledge_id"] for d in retriever.retrieve(q["q"], k=k, mode=mode, min_score=0.0)]
        rank = next((i + 1 for i, kid in enumerate(ids) if kid in q["gold"]), None)
        if rank:
            hits += 1
            rr += 1.0 / rank
        else:
            misses.append({"question": q["q"], "expected": q["gold"], "got": ids[:3]})
    n = len(qs)
    return {"mode": mode, "questions": n, "recall_at_5": round(hits / n, 3), "mrr": round(rr / n, 3), "misses": misses}


def main() -> int:
    modes = ["bm25"] + (["embed", "hybrid"] if retriever.embeddings_available() else [])
    results = {m: evaluate(m) for m in modes}
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "retrieval_mode": retriever.retrieval_mode(),
              "knowledge_notes": len(retriever.load_kb()), "results": results}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    for m, r in results.items():
        print(f"{m:7s}  Recall@5 {r['recall_at_5']:.0%}   MRR {r['mrr']:.2f}   ({r['questions']} questions)")
    if not retriever.embeddings_available():
        print("embedding model not installed -> BM25 only (pip install the en_core_web_md wheel to enable hybrid)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
