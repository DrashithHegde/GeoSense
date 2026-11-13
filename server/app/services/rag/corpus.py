"""Document ingestion for RAG: download -> extract text per page -> clean -> chunk -> embed -> store.

* Download: each document's URLs are tried in order; the PDF is cached in data/rag/corpus/raw
  with its SHA-256, so re-runs do not download again.
* Extract: pypdf, page by page (page numbers are kept for citations). HTML pages: paragraph text.
* Clean: join hyphenated line breaks, collapse whitespace, drop pages that are mostly a
  reference list, table of contents or too short to carry meaning.
* Chunk: ~180-word passages with a 40-word overlap, never crossing a page boundary, so every
  passage can be cited as "document, p. N".
* Embed + store: see vector_store.py (pgvector with an HNSW index, or an in-memory fallback).
"""
from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

SERVER_ROOT = Path(__file__).resolve().parents[3]
SOURCES = Path(__file__).parent / "corpus_sources.json"
CORPUS_DIR = SERVER_ROOT / "data" / "rag" / "corpus"
RAW_DIR = CORPUS_DIR / "raw"
PASSAGES = CORPUS_DIR / "passages.jsonl"
CHUNK_WORDS = 180
OVERLAP_WORDS = 40
MIN_PAGE_WORDS = 60
USER_AGENT = "GeoSense-research-ingest/1.0 (academic project; respects robots and caches files)"


def load_sources(path: Path = SOURCES) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))["documents"]


# ── download ──────────────────────────────────────────────────────────────────

def download(doc: dict, raw_dir: Path = RAW_DIR, timeout: float = 90.0) -> tuple[Path | None, str | None]:
    import requests

    raw_dir.mkdir(parents=True, exist_ok=True)
    ext = ".pdf" if doc["type"] == "pdf" else ".html"
    path = raw_dir / f"{doc['id']}{ext}"
    if path.exists() and path.stat().st_size > 1000:
        return path, "cached"
    errors = []
    for url in doc["urls"]:
        try:
            r = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT}, allow_redirects=True)
            r.raise_for_status()
            body = r.content
            if doc["type"] == "pdf" and not body[:5] == b"%PDF-":
                errors.append(f"{url}: not a PDF")
                continue
            path.write_bytes(body)
            return path, url
        except Exception as exc:  # try the next mirror
            errors.append(f"{url}: {exc!s:.80}")
    return None, "; ".join(errors)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ── extract ───────────────────────────────────────────────────────────────────

class _Paragraphs(HTMLParser):
    KEEP = {"p", "li", "h1", "h2", "h3", "h4", "blockquote", "figcaption"}

    def __init__(self):
        super().__init__()
        self.out: list[str] = []
        self._buf: list[str] = []
        self._depth = 0
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "footer", "header"):
            self._skip += 1
        if tag in self.KEEP:
            self._depth += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "header") and self._skip:
            self._skip -= 1
        if tag in self.KEEP and self._depth:
            self._depth -= 1
            t = " ".join("".join(self._buf).split())
            if len(t.split()) >= 8:
                self.out.append(t)
            self._buf = []

    def handle_data(self, data):
        if self._depth and not self._skip:
            self._buf.append(data)


def extract_pages(path: Path, kind: str) -> list[tuple[int, str]]:
    """[(page_number, text)] — HTML is treated as one 'page' per ~600 words."""
    if kind == "pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)]
    parser = _Paragraphs()
    parser.feed(path.read_text(encoding="utf-8", errors="ignore"))
    words = " ".join(parser.out).split()
    return [(i // 600 + 1, " ".join(words[i:i + 600])) for i in range(0, len(words), 600)]


# ── clean ─────────────────────────────────────────────────────────────────────

_REF_LINE = re.compile(r"(\(\d{4}[a-z]?\)|\b(19|20)\d{2}[a-z]?\.|doi:|https?://|et al\.)", re.I)


def clean_page(text: str) -> str | None:
    text = text.replace("­", "")
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)          # join hyphenated line breaks
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return None
    head = " ".join(lines[:2]).lower()
    if head.startswith(("references", "bibliography", "contents", "table of contents", "acknowledg")):
        return None
    refish = sum(1 for ln in lines if _REF_LINE.search(ln)) / len(lines)
    if refish > 0.45 and len(lines) > 8:                         # a reference list, not content
        return None
    dots = sum(1 for ln in lines if re.search(r"\.{5,}\s*\d+$", ln)) / len(lines)
    if dots > 0.3:                                               # table of contents
        return None
    out = " ".join(" ".join(lines).split())
    return out if len(out.split()) >= MIN_PAGE_WORDS else None


def chunk(text: str, size: int = CHUNK_WORDS, overlap: int = OVERLAP_WORDS) -> list[str]:
    words = text.split()
    if len(words) <= size:
        return [" ".join(words)]
    step = size - overlap
    out = []
    for i in range(0, len(words), step):
        part = words[i:i + size]
        if len(part) < 40 and out:      # tiny tail: merge into the previous passage
            out[-1] = out[-1] + " " + " ".join(part)
            break
        out.append(" ".join(part))
        if i + size >= len(words):
            break
    return out


def passages_for(doc: dict, pages: list[tuple[int, str]]) -> list[dict[str, Any]]:
    out = []
    for page, raw in pages:
        text = clean_page(raw)
        if not text:
            continue
        for j, part in enumerate(chunk(text)):
            out.append({"id": f"{doc['id']}:p{page}:{j}", "doc_id": doc["id"], "kind": "passage", "page": page,
                        "title": doc["title"], "citation": doc["citation"], "source_type": doc["source_type"],
                        "url": doc.get("landing") or doc["urls"][0], "doi": doc.get("doi"),
                        "supports": doc.get("supports", []), "text": part})
    return out


def build_passages(sources: list[dict] | None = None, log=print) -> tuple[list[dict], list[dict]]:
    """Download + extract + chunk every source. Returns (passages, per-document report)."""
    sources = sources or load_sources()
    passages, report = [], []
    for doc in sources:
        path, how = download(doc)
        if not path:
            report.append({"id": doc["id"], "status": "download_failed", "detail": how})
            log(f"  ✗ {doc['id']}: could not download ({how})")
            continue
        try:
            pages = extract_pages(path, doc["type"])
        except Exception as exc:
            report.append({"id": doc["id"], "status": "extract_failed", "detail": str(exc)[:200]})
            log(f"  ✗ {doc['id']}: text extraction failed ({exc!s:.80})")
            continue
        ps = passages_for(doc, pages)
        passages.extend(ps)
        report.append({"id": doc["id"], "status": "ok", "pages": len(pages), "passages": len(ps),
                       "sha256": sha256(path), "from": how})
        log(f"  ✓ {doc['id']}: {len(pages)} pages -> {len(ps)} passages")
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    PASSAGES.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in passages), encoding="utf-8")
    (CORPUS_DIR / "ingest_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return passages, report


def load_passages(path: Path = PASSAGES) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
