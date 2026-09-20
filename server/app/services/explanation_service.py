"""Orchestrator for the GeoSense explanation layer.

Combines the deterministic evidence engine, knowledge retrieval, and optional LLM
layer into a single response object. Validates LLM output against evidence.
"""
from __future__ import annotations

import re
import json
from typing import Any, Dict

from app.services.explanation_evidence import build_zone_evidence
from app.services.explanation_engine import generate_deterministic_explanation
from app.services.rag_knowledge import get_knowledge_context
from app.services.llm_client import generate_llm_explanation, LLMUnavailable, InvalidLLMResponse


def _validate_llm_explanation(llm_expl: dict[str, Any], evidence: dict[str, Any]) -> list[str]:
    """Validate LLM output to ensure it doesn't invent missing data or contradict evidence."""
    warnings = []
    
    full_text = json.dumps(llm_expl).lower()
    
    measurements = evidence.get("measurements", {})
    
    # 1. Null hallucination checks
    if measurements.get("lst") is None and "lst" in full_text and "unavailable" not in full_text:
        warnings.append("hallucination: LLM mentioned LST but LST is null in evidence.")
        
    if measurements.get("aqi") is None and "aqi" in full_text and "unavailable" not in full_text:
        warnings.append("hallucination: LLM mentioned AQI but AQI is null in evidence.")
        
    # 2. Value alteration checks using regex for metrics
    # Extract numbers near metric names, e.g., "aqi of 120", "lst is 34.2", "ndvi = 0.5"
    metrics = {"aqi": r"aqi[^\d]{1,15}(\d+(?:\.\d+)?)",
               "lst": r"lst[^\d]{1,15}(\d+(?:\.\d+)?)", 
               "ndvi": r"ndvi[^\d]{1,15}(-?\d+(?:\.\d+)?)",
               "ndwi": r"ndwi[^\d]{1,15}(-?\d+(?:\.\d+)?)",
               "mndwi": r"mndwi[^\d]{1,15}(-?\d+(?:\.\d+)?)",
               "ndci": r"ndci[^\d]{1,15}(-?\d+(?:\.\d+)?)",
               "turbidity_proxy": r"turbidity[^\d]{1,15}(-?\d+(?:\.\d+)?)",
               "water_health_score": r"water health score[^\d]{1,15}(-?\d+(?:\.\d+)?)"}
    
    for metric, pattern in metrics.items():
        actual_val = measurements.get(metric)
        if actual_val is not None:
            matches = re.findall(pattern, full_text)
            for match in matches:
                try:
                    claimed_val = float(match)
                    # allow a small epsilon for floating point rounding
                    if abs(claimed_val - float(actual_val)) > 0.1:
                        warnings.append(f"hallucination: LLM claimed {metric} is {claimed_val} but actual is {actual_val}")
                except ValueError:
                    pass

    # 3. Check anomaly classification change
    classification = "anomaly" if evidence.get("isolation_forest", {}).get("is_anomaly") else "inlier"
    if classification == "inlier" and "anomal" in full_text:
        warnings.append("hallucination: LLM mentioned anomaly for an inlier zone.")

    # 4. Check for forbidden causal language
    forbidden_phrases = ["caused by", "because of", "responsible for"]
    for phrase in forbidden_phrases:
        if phrase in full_text:
            warnings.append(f"causal language: LLM used forbidden causal language: '{phrase}'.")
            
    return warnings


async def build_full_explanation(db, zone_id: int) -> Dict[str, Any]:
    """Assemble the complete explanation response including optional LLM insights."""
    # 1. Retrieve and validate evidence (Authoritative)
    evidence = build_zone_evidence(db, zone_id)
    
    city = evidence.get("zone", {}).get("city", "Mumbai")
    
    # 2. Generate deterministic explanation (Ground Truth)
    deterministic_text = generate_deterministic_explanation(evidence)
    
    # 3. Retrieve knowledge context
    knowledge_context = get_knowledge_context(evidence, city=city)
    
    llm_explanation = None
    warnings = []
    generation_status = "llm_success"
    
    # 4. Call LLM
    try:
        llm_explanation = await generate_llm_explanation(evidence, knowledge_context, deterministic_text)
        
        # 5. Validate LLM output
        llm_warnings = _validate_llm_explanation(llm_explanation, evidence)
        if llm_warnings:
            warnings.extend(llm_warnings)
            if any("causal language" in w or "hallucination" in w for w in llm_warnings):
                llm_explanation = None
                generation_status = "llm_validation_failed"
                warnings.append("LLM explanation rejected due to failed validation constraints.")
    
    except LLMUnavailable as e:
        if "GEMINI_API_KEY is not configured" in str(e):
            generation_status = "llm_not_configured"
        else:
            generation_status = "llm_unavailable"
            warnings.append(str(e))
    except InvalidLLMResponse as e:
        generation_status = "llm_validation_failed"
        warnings.append(str(e))
    except Exception as e:
        generation_status = "llm_error"
        warnings.append(f"Unexpected LLM error: {e}")

    result = {
        "zone_id": zone_id,
        "zone_name": evidence.get("zone", {}).get("name"),
        "city": city,
        "analysis_timestamp": evidence.get("analysis_timestamp"),
        "classification": "anomaly" if evidence.get("isolation_forest", {}).get("is_anomaly") else "inlier",
        "deterministic_explanation": deterministic_text,
        "knowledge_context": knowledge_context,
        "generation_status": generation_status,
        "warnings": warnings,
        "evidence": evidence,
        "limitations": evidence.get("limitations", []),
        "provenance": evidence.get("provenance", {})
    }
    
    if llm_explanation:
        result["llm_explanation"] = llm_explanation
        
    return result
