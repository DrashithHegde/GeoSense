"""Guardrails for every AI interaction in GeoSense (input → retrieval → output), plus rate limiting.

The same four rail types as NVIDIA NeMo Guardrails, implemented as deterministic, testable Python
instead of extra LLM "self-check" calls (no added latency, no extra API quota, same result every
time, and no heavy native dependency on Windows):

  1. INPUT rail      check_question()      prompt injection / jailbreak, secrets probing, abuse,
                                             code or markup, length and character sanity
  2. RETRIEVAL rail  sanitize_passages()   retrieved text is DATA, never instructions: lines that try
                                             to instruct the model are removed, size capped, only known
                                             sources (curated notes + corpus_sources.json documents)
  3. OUTPUT rail     parse_*() (Pydantic)  the model's JSON must match a strict schema (types, word
                                             limits, citation ids); then explainer.validate_llm() checks
                                             every number, citation, causal claim and model-flag claim
                                             against the evidence; scan_output() blocks leaked secrets,
                                             links and markup
  4. RATE LIMIT      RateLimiter           per-client sliding window on the AI endpoints

Every block is logged to data/logs/guardrails.jsonl (time, rail, reason, first 200 characters) so
attempts can be audited. No personal data is stored.
"""
from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

LOG_PATH = Path(__file__).resolve().parents[3] / "data" / "logs" / "guardrails.jsonl"
_log_lock = threading.Lock()


def log_event(rail: str, reason: str, text: str = "", **extra: Any) -> None:
    rec = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rail": rail, "reason": reason,
           "text": (text or "")[:200], **extra}
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _log_lock, LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass  # logging must never break a request


# ── 1. INPUT rail ─────────────────────────────────────────────────────────────

# Prompt-injection / jailbreak phrasings (OWASP LLM01). Matched on a normalised, lower-case copy.
_INJECTION = [
    r"\b(ignore|disregard|forget|override|bypass)\b.{0,40}\b(previous|prior|above|earlier|all|your|the|these|system)\b"
    r".{0,25}\b(instruction|instructions|rules|prompt|prompts|guideline|guidelines|directions|context)\b",
    r"\b(you are|you're|act as|pretend (to be|you are)|roleplay as|from now on you)\b.{0,40}"
    r"\b(dan|jailbroken|unfiltered|uncensored|developer mode|evil|without (any )?(rules|restrictions|limits))\b",
    r"\b(reveal|show|print|repeat|output|leak|tell me|what is|what are)\b.{0,30}"
    r"\b(system prompt|hidden prompt|initial prompt|your (instructions|prompt|rules)|developer message)\b",
    r"\b(api[ _-]?key|secret key|access token|password|credentials?)\b|(^|[\s/\\])\.env\b",
    r"\bdeveloper mode\b|\bjailbreak\b|\bdo anything now\b",
    r"<\s*/?\s*(system|assistant|user|im_start|im_end)\s*>|\[/?(inst|sys)\]|<<\s*sys\s*>>",
    r"^\s*(system|assistant)\s*:",
    r"\bnew (instructions|rules|task)\s*:",
    r"\b(respond|answer|reply) only with\b.{0,40}\b(yes|ok|true|the following)\b",
]
_INJECTION_RE = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in _INJECTION]

# Code / markup that has no place in a question about a map location.
_CODE_RE = re.compile(r"<\s*(script|iframe|img|svg|object|embed)\b|javascript:|```|\bimport\s+os\b|"
                      r"\b(drop|delete|truncate)\s+table\b|\bunion\s+select\b|;\s*--", re.IGNORECASE)

# Minimal abuse list (English + common Hindi/Marathi transliterations). Not a moral filter — it only
# stops abusive text being sent to the AI provider.
_ABUSE = ["fuck", "fucking", "motherfucker", "bitch", "bastard", "cunt", "asshole", "dickhead", "slut", "whore",
          "madarchod", "behenchod", "bhenchod", "chutiya", "chutiye", "gandu", "randi", "bhosdi", "lavda", "lauda"]
_ABUSE_RE = re.compile(r"\b(" + "|".join(map(re.escape, _ABUSE)) + r")\b", re.IGNORECASE)


class Verdict(BaseModel):
    allowed: bool
    rail: str = "input"
    category: str | None = None   # injection | secrets | code | abuse | malformed
    message: str | None = None    # what the user is told


def normalise(text: str) -> str:
    """NFKC (folds look-alike Unicode), drop zero-width / control characters, collapse spaces."""
    t = unicodedata.normalize("NFKC", text or "")
    t = "".join(ch for ch in t if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    return re.sub(r"[ \t]+", " ", t).strip()


def check_question(question: str) -> Verdict:
    q = normalise(question)
    low = q.lower()
    if len(q) < 3 or not re.search(r"[a-zA-Zऀ-ॿ]", q):
        return _block("malformed", "Please type a question about this location.", q)
    if len(re.findall(r"[^\w\s.,?!'\"°%()/:-]", q)) > max(12, len(q) // 5):
        return _block("malformed", "Please type a question about this location in plain words.", q)
    if any(r.search(low) for r in _INJECTION_RE):
        cat = "secrets" if re.search(r"api[ _-]?key|secret key|access token|password|\.env\b|credential", low) else "injection"
        return _block(cat, "I can only answer questions about this location's environmental data and the cited "
                           "knowledge base, so I can't follow instructions that change how I work.", q)
    if _CODE_RE.search(q):
        return _block("code", "Please ask in plain words — code and markup are not accepted.", q)
    if _ABUSE_RE.search(low):
        return _block("abuse", "Please rephrase your question without abusive language.", q)
    return Verdict(allowed=True)


def _block(category: str, message: str, text: str) -> Verdict:
    log_event("input", category, text)
    return Verdict(allowed=False, category=category, message=message)


# ── 2. RETRIEVAL rail ─────────────────────────────────────────────────────────

_ALLOWED_DOCS: set[str] | None = None


def _allowed_docs() -> set[str]:
    """Documents we chose to ingest (corpus_sources.json). Anything else is never sent to the AI."""
    global _ALLOWED_DOCS
    if _ALLOWED_DOCS is None:
        p = Path(__file__).parent / "corpus_sources.json"
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            docs = raw.get("documents", raw) if isinstance(raw, dict) else raw
            _ALLOWED_DOCS = {d["id"] for d in docs if isinstance(d, dict) and d.get("id")}
        except (OSError, ValueError, KeyError):
            _ALLOWED_DOCS = set()
    return _ALLOWED_DOCS


def sanitize_passages(passages: list[dict], max_chars: int = 700) -> list[dict]:
    """Retrieved text is evidence, not instructions.

    * keeps curated notes and passages from known documents only
    * removes any line that reads like an instruction to an AI (indirect prompt injection, OWASP LLM01)
    * strips markup and caps the length sent to the model
    """
    allowed_docs = _allowed_docs()
    clean = []
    for p in passages:
        kind = p.get("kind", "note")
        if kind == "passage" and allowed_docs and p.get("doc_id") not in allowed_docs:
            log_event("retrieval", "unknown_source", p.get("knowledge_id", ""), doc_id=p.get("doc_id"))
            continue
        text = p.get("content") or ""
        kept, dropped = [], 0
        for line in re.split(r"(?<=[.!?])\s+|\n", text):
            if any(r.search(line.lower()) for r in _INJECTION_RE) or _CODE_RE.search(line):
                dropped += 1
                continue
            kept.append(line)
        if dropped:
            log_event("retrieval", "instruction_like_text_removed", p.get("knowledge_id", ""), lines=dropped)
        body = re.sub(r"<[^>]{0,200}>", " ", " ".join(kept))
        body = re.sub(r"\s+", " ", body).strip()[:max_chars]
        if body:
            clean.append({**p, "content": body})
    return clean


# ── 3. OUTPUT rail (Pydantic) ─────────────────────────────────────────────────

_SECRET_RE = re.compile(r"\b(AIza[0-9A-Za-z_\-]{20,}|gsk_[0-9A-Za-z]{20,}|sk-[0-9A-Za-z_\-]{20,}|"
                        r"pk\.eyJ[0-9A-Za-z_\-.]{20,}|AccountKey=[^;\s]+)", re.IGNORECASE)
_LINK_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
_MARKUP_RE = re.compile(r"<\s*/?\s*[a-z][^>]{0,100}>|```", re.IGNORECASE)
_KID_RE = r"^[A-Za-z0-9_.:\-]{1,80}$"


class SummaryOut(BaseModel):
    """What the AI may return for the plain-words summary."""
    plain_summary: str = Field(..., min_length=1, max_length=700)

    @field_validator("plain_summary")
    @classmethod
    def _words(cls, v: str) -> str:
        v = v.strip()
        if len(v.split()) > 90:
            raise ValueError("more than 90 words")
        return v


class AnswerOut(BaseModel):
    """What the AI may return for an Ask GeoSense answer."""
    answer: str = Field(..., min_length=1, max_length=900)
    citations: list[str] = Field(default_factory=list, max_length=6)

    @field_validator("answer")
    @classmethod
    def _words(cls, v: str) -> str:
        v = v.strip()
        if v != "OUT_OF_SCOPE" and len(v.split()) > 110:
            raise ValueError("more than 110 words")
        return v

    @field_validator("citations")
    @classmethod
    def _ids(cls, v: list[str]) -> list[str]:
        for c in v:
            if not re.match(_KID_RE, str(c)):
                raise ValueError(f"malformed citation id {c!r}")
        return v


def scan_output(text: str) -> list[str]:
    """Things that must never reach the screen, whatever the evidence says."""
    problems = []
    if _SECRET_RE.search(text or ""):
        problems.append("looks like a secret / API key")
    if _LINK_RE.search(text or ""):
        problems.append("contains a link (sources are shown separately)")
    if _MARKUP_RE.search(text or ""):
        problems.append("contains markup or code")
    if any(r.search((text or "").lower()) for r in _INJECTION_RE[:3]):
        problems.append("echoes instructions")
    return problems


def parse_output(model: type[BaseModel], raw: dict) -> tuple[BaseModel | None, list[str]]:
    """Validate the model's JSON against a strict schema; returns (object | None, problems)."""
    try:
        obj = model.model_validate(raw if isinstance(raw, dict) else {})
    except ValidationError as exc:
        probs = [f"schema: {e['loc'][0] if e.get('loc') else ''} {e['msg']}".strip() for e in exc.errors()[:3]]
        log_event("output", "schema", json.dumps(raw, ensure_ascii=False, default=str)[:200])
        return None, probs
    text = " ".join(str(v) for v in obj.model_dump().values())
    probs = scan_output(text)
    if probs:
        log_event("output", "; ".join(probs), text)
        return None, probs
    return obj, []


# ── 4. RATE LIMIT ─────────────────────────────────────────────────────────────

class RateLimiter:
    """Sliding-window limit per client (IP). In memory: right for one server process."""

    def __init__(self, limit: int, window_s: float):
        self.limit, self.window = limit, window_s
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, float]:
        """(allowed, seconds until the next request would be allowed)."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False, max(0.0, self.window - (now - q[0]))
            q.append(now)
            return True, 0.0


ASK_LIMIT = RateLimiter(limit=20, window_s=60.0)        # Ask GeoSense: 20 questions / minute / client
AI_SUMMARY_LIMIT = RateLimiter(limit=40, window_s=60.0)  # AI summaries in Deep Analysis
