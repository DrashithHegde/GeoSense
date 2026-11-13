"""Text embedding models for RAG (pluggable, offline after the first download).

Preferred: BAAI/bge-small-en-v1.5 via FastEmbed (ONNX, CPU, 384-d sentence embeddings; Xiao et
al. 2023, "C-Pack: Packaged resources to advance general Chinese embedding", arXiv:2309.07597).
The model (~130 MB) is downloaded once on first use and cached locally.
Fallback: spaCy en_core_web_md (300-d mean of word vectors) — always available offline.

Choose with RAG_EMBEDDER = auto | bge-small | spacy | off   (default auto: bge-small, else spaCy).
All vectors are L2-normalised, so cosine similarity = dot product.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import numpy as np

MODEL_DIR = Path(__file__).resolve().parents[3] / "data" / "rag" / "models"

BGE_MODEL = "BAAI/bge-small-en-v1.5"
# BGE retrieval models expect this instruction on short queries (not on passages)
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def _norm(m: np.ndarray) -> np.ndarray:
    m = np.asarray(m, dtype="float32")
    if m.ndim == 1:
        n = float(np.linalg.norm(m))
        return m / n if n else m
    n = np.linalg.norm(m, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return m / n


class Embedder:
    name: str = "base"
    dim: int = 0
    min_cos: float = 0.5   # an embedding-only match must be at least this similar

    def embed_docs(self, texts: list[str]) -> np.ndarray:  # pragma: no cover - interface
        raise NotImplementedError

    def embed_query(self, text: str) -> np.ndarray:  # pragma: no cover - interface
        raise NotImplementedError


class BgeEmbedder(Embedder):
    name, dim, min_cos = "bge-small-en-v1.5", 384, 0.62

    def __init__(self, allow_download: bool = False):
        from fastembed import TextEmbedding
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        # at runtime only a model already on disk is used (no network wait); the ingestion
        # script downloads it once with allow_download=True
        self.model = TextEmbedding(model_name=BGE_MODEL, cache_dir=str(MODEL_DIR),
                                   local_files_only=not allow_download)
        probe = list(self.model.embed(["probe"]))[0]
        self.dim = int(len(probe))

    def embed_docs(self, texts):
        return _norm(np.vstack(list(self.model.embed(list(texts), batch_size=64))))

    def embed_query(self, text):
        return _norm(np.asarray(list(self.model.embed([BGE_QUERY_PREFIX + text]))[0]))


class SpacyEmbedder(Embedder):
    name, dim, min_cos = "spacy-en_core_web_md", 300, 0.55

    def __init__(self):
        import spacy
        self.nlp = spacy.load("en_core_web_md", exclude=["parser", "ner", "tagger", "lemmatizer",
                                                         "attribute_ruler", "senter", "morphologizer"])

    def _one(self, doc) -> np.ndarray:
        vecs = [t.vector for t in doc if t.has_vector and not t.is_stop and not t.is_punct and not t.like_num]
        return _norm(np.mean(vecs, axis=0) if vecs else doc.vector)

    def embed_docs(self, texts):
        return np.vstack([self._one(d) for d in self.nlp.pipe(list(texts), batch_size=64)])

    def embed_query(self, text):
        return self._one(self.nlp(text))


@lru_cache(maxsize=2)
def get_embedder(allow_download: bool = False) -> Embedder | None:
    choice = os.getenv("RAG_EMBEDDER", os.getenv("RAG_EMBEDDINGS", "auto")).lower()
    if choice == "off":
        return None
    if choice in ("auto", "bge-small", "on"):
        try:
            return BgeEmbedder(allow_download=allow_download)
        except Exception:  # fastembed not installed / model not on disk -> fall back
            if choice == "bge-small":
                raise
    try:
        return SpacyEmbedder()
    except Exception:
        return None
