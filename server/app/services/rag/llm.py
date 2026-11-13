"""Provider-agnostic LLM client (optional) with automatic fallback.

Every configured provider is tried in order until one answers:
    ANTHROPIC_API_KEY -> GEMINI_API_KEY -> GROQ_API_KEY -> OPENAI_API_KEY
A rate limit (HTTP 429) or outage on one provider moves on to the next. If none
is configured or all fail, callers fall back to the deterministic,
evidence-only explanation: nothing is invented either way, and every LLM answer
is still checked by the validator in explainer.py.

Model names can be overridden per provider: ANTHROPIC_MODEL, GEMINI_MODEL,
GROQ_MODEL, OPENAI_MODEL (LLM_MODEL overrides the first provider only).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from typing import Any

import httpx

from app.core.config import get_settings


class LLMUnavailable(Exception):
    pass


DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5-5",
    "gemini": "gemini-2.5-flash",
    "groq": "llama-3.3-70b-versatile",
    "openai": "gpt-4o-mini",
}
KEY_NAMES = {
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "openai": "OPENAI_API_KEY",
}
ORDER = ("anthropic", "gemini", "groq", "openai")


def _env(name: str) -> str | None:
    s = get_settings()
    return getattr(s, name.lower(), None) or os.getenv(name)


def configured_providers() -> list[tuple[str, str]]:
    out = []
    for i, p in enumerate(ORDER):
        if _env(KEY_NAMES[p]):
            model = _env(f"{p.upper()}_MODEL") or (_env("LLM_MODEL") if not out else None) or DEFAULT_MODELS[p]
            out.append((p, model))
    return out


def active_provider() -> tuple[str, str] | None:
    provs = configured_providers()
    return provs[0] if provs else None


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in LLM output")
    return json.loads(m.group(0))


# Model ids get retired; when a configured model returns 404 we ask the provider
# which models exist and pick the best available chat model.
_RESOLVED_MODEL: dict[str, str] = {}
_PREFERRED = {
    "groq": ("llama-3.3-70b-versatile", "openai/gpt-oss-120b", "meta-llama/llama-4-maverick", "llama-4",
             "gpt-oss-120b", "gpt-oss", "qwen", "kimi", "llama"),
    "openai": ("gpt-4o-mini", "gpt-4.1-mini", "gpt-5-mini", "gpt-4o", "gpt"),
}
_NOT_CHAT = ("whisper", "guard", "tts", "embed", "audio", "vision-preview", "distil", "prompt")


async def _discover_model(client: httpx.AsyncClient, provider: str, key: str) -> str | None:
    url = ("https://api.groq.com/openai/v1/models" if provider == "groq" else "https://api.openai.com/v1/models")
    r = await client.get(url, headers={"Authorization": f"Bearer {key}"})
    r.raise_for_status()
    ids = [m.get("id", "") for m in r.json().get("data", []) if m.get("active", True)]
    ids = [i for i in ids if not any(x in i.lower() for x in _NOT_CHAT)]
    for pref in _PREFERRED.get(provider, ()):
        for i in ids:
            if pref in i:
                return i
    return ids[0] if ids else None


_CACHE: dict[str, tuple[float, tuple[dict[str, Any], dict[str, str]]]] = {}
_CACHE_TTL_S = 3600.0
# After a 429, skip that provider for a while instead of hammering it.
_COOLDOWN: dict[str, float] = {}
_COOLDOWN_S = 30.0
_MAX_WAIT_S = 12.0  # a short Retry-After (typical for per-minute token limits) is worth waiting for


def _retry_after(resp) -> float | None:
    h = getattr(resp, "headers", None) or {}
    for k in ("retry-after", "Retry-After", "x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
        v = h.get(k) if hasattr(h, "get") else None
        if not v:
            continue
        m = re.match(r"^\s*(?:(\d+(?:\.\d+)?)m)?\s*(\d+(?:\.\d+)?)?s?\s*$", str(v))
        try:
            if m and (m.group(1) or m.group(2)):
                return float(m.group(1) or 0) * 60 + float(m.group(2) or 0)
            return float(v)
        except ValueError:
            continue
    return None


def _scrub(message: str) -> str:
    """Never let an API key reach the UI or logs."""
    message = re.sub(r"([?&]key=)[^&\s']+", r"\1***", message)
    for name in KEY_NAMES.values():
        v = _env(name)
        if v:
            message = message.replace(v, "***")
    return message


async def complete_json(system: str, user: str, timeout: float = 30.0) -> tuple[dict[str, Any], dict[str, str]]:
    provs = configured_providers()
    if not provs:
        raise LLMUnavailable("No LLM API key configured (ANTHROPIC / GEMINI / GROQ / OPENAI).")
    cache_key = hashlib.sha256(f"{system}|{user}".encode()).hexdigest()
    hit = _CACHE.get(cache_key)
    if hit and time.time() - hit[0] < _CACHE_TTL_S:
        return hit[1]

    failures: list[str] = []
    for provider, model in provs:
        if time.time() < _COOLDOWN.get(provider, 0):
            failures.append(f"{provider}: rate-limited, skipped")
            continue
        for attempt in range(2):
            try:
                result = await _call(provider, model, system, user, timeout)
                if failures:
                    result[1]["fallback_from"] = "; ".join(failures)
                _CACHE[cache_key] = (time.time(), result)
                return result
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                if code == 429:
                    wait = _retry_after(exc.response)
                    if attempt == 0 and wait is not None and wait <= _MAX_WAIT_S:
                        await asyncio.sleep(wait + 0.5)
                        continue
                    _COOLDOWN[provider] = time.time() + max(_COOLDOWN_S, min(wait or 0, 120))
                    failures.append(f"{provider}: rate limit (429)")
                    break
                if code in (500, 502, 503, 504) and attempt == 0:
                    await asyncio.sleep(1.5)
                    continue
                failures.append(f"{provider}: HTTP {code}")
                break
            except httpx.HTTPError as exc:
                failures.append(f"{provider}: {_scrub(type(exc).__name__)}")
                break
            except (ValueError, KeyError, IndexError, json.JSONDecodeError):
                failures.append(f"{provider}: malformed output")
                break
    raise LLMUnavailable("All AI providers unavailable right now (" + "; ".join(failures) +
                         "). Showing the evidence-only write-up.")


async def _call(provider: str, model: str, system: str, user: str, timeout: float):
    key = _env(KEY_NAMES[provider])
    async with httpx.AsyncClient(timeout=timeout) as client:
        if provider == "anthropic":
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": model, "max_tokens": 1500, "temperature": 0.1, "system": system,
                      "messages": [{"role": "user", "content": user}]},
            )
            r.raise_for_status()
            text = "".join(b.get("text", "") for b in r.json().get("content", []))
        elif provider == "gemini":
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": key},
                json={"systemInstruction": {"parts": [{"text": system}]},
                      "contents": [{"parts": [{"text": user}]}],
                      "generationConfig": {"temperature": 0.1, "response_mime_type": "application/json"}},
            )
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        else:  # groq and openai share the OpenAI chat-completions format
            url = ("https://api.groq.com/openai/v1/chat/completions" if provider == "groq"
                   else "https://api.openai.com/v1/chat/completions")
            model = _RESOLVED_MODEL.get(provider, model)

            async def send(m: str):
                return await client.post(
                    url, headers={"Authorization": f"Bearer {key}"},
                    json={"model": m, "temperature": 0.1, "response_format": {"type": "json_object"},
                          "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
                )

            r = await send(model)
            if r.status_code in (400, 404):
                found = await _discover_model(client, provider, key)
                if found and found != model:
                    _RESOLVED_MODEL[provider] = model = found
                    r = await send(model)
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
    return _extract_json(text), {"provider": provider, "model": model}
