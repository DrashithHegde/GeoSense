"""LLM client and provider abstraction for the GeoSense explanation layer.

Provides a city-agnostic, provider-agnostic interface for generating
evidence-grounded explanations. Implements a Gemini REST provider using httpx.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
import httpx

from app.core.config import get_settings


class LLMUnavailable(Exception):
    """Raised when the LLM cannot be reached or is not configured."""
    pass


class InvalidLLMResponse(Exception):
    """Raised when the LLM returns an invalid or malformed response."""
    pass


def _build_prompt(
    evidence: dict[str, Any],
    knowledge_context: List[Dict[str, Any]],
    deterministic_text: str,
) -> str:
    """Build the strict prompt constraining the LLM to facts and evidence."""
    evidence_json = json.dumps(evidence, indent=2, default=str)
    knowledge_json = json.dumps(knowledge_context, indent=2, default=str)
    
    city = evidence.get("zone", {}).get("city", "Mumbai") # Default fallback

    prompt = f"""You are an environmental data analyst assistant for GeoSense, monitoring {city}.
You will be given verified sensor measurements, model outputs, and curated scientific context.
Your job is to write a clear, evidence-grounded explanation of environmental conditions for a specific zone.

RULES (never violate):
1. Never invent measurements. Every numerical claim must come exactly from OBSERVATIONS or MODEL_SIGNALS.
2. Never claim physical causation. Use "associated with", "coincides with", "the model identifies". Avoid "X caused Y".
3. If a value is marked as unavailable or null, say it is unavailable. Do not fill in a substitute, do not invent a temperature.
4. Distinguish: OBSERVATION (measured), MODEL_SIGNAL (Isolation Forest output), EXTERNAL_KNOWLEDGE (retrieved context).
5. Do not upgrade IDW-estimated AQI to "observed".

EVIDENCE OBJECT (JSON):
{evidence_json}

KNOWLEDGE CONTEXT (JSON):
{knowledge_json}

DETERMINISTIC FALLBACK (For Reference):
{deterministic_text}

OUTPUT FORMAT:
Return ONLY a valid JSON object matching this schema, without any markdown formatting or code blocks:
{{
  "summary": "<1-2 sentence plain summary>",
  "observations_paragraph": "<paragraph about measurements>",
  "model_signals_paragraph": "<paragraph about IF deviations, if any>",
  "temporal_paragraph": "<paragraph about trends, or explicit unavailability>",
  "knowledge_context_used": ["<list of knowledge_id actually referenced>"],
  "warnings": ["<any self-identified caveats or limitations>"]
}}
"""
    return prompt


async def call_gemini(
    evidence: dict[str, Any],
    knowledge_context: List[Dict[str, Any]],
    deterministic_text: str,
) -> Dict[str, Any]:
    """Call the Gemini REST API using httpx."""
    settings = get_settings()
    api_key = settings.gemini_api_key

    if not api_key:
        raise LLMUnavailable("GEMINI_API_KEY is not configured.")

    prompt = _build_prompt(evidence, knowledge_context, deterministic_text)
    
    # Use gemini-2.0-flash-lite or gemini-1.5-flash as default fast models
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "response_mime_type": "application/json"
        }
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException as exc:
        raise LLMUnavailable(f"LLM request timed out: {exc}") from exc
    except httpx.HTTPError as exc:
        raise LLMUnavailable(f"LLM request failed: {exc}") from exc

    try:
        # Extract text from Gemini response structure
        candidates = data.get("candidates", [])
        if not candidates:
            raise InvalidLLMResponse("No candidates returned from Gemini.")
            
        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        if not parts:
            raise InvalidLLMResponse("No text parts returned from Gemini.")
            
        text = parts[0].get("text", "")
        
        # Parse JSON
        result = json.loads(text)
        return result
    except json.JSONDecodeError as exc:
        raise InvalidLLMResponse("LLM returned malformed JSON.") from exc
    except Exception as exc:
        raise InvalidLLMResponse(f"Failed to parse LLM response: {exc}") from exc


async def generate_llm_explanation(
    evidence: dict[str, Any],
    knowledge_context: List[Dict[str, Any]],
    deterministic_text: str,
) -> Dict[str, Any]:
    """Provider interface for generating LLM explanation."""
    return await call_gemini(evidence, knowledge_context, deterministic_text)
