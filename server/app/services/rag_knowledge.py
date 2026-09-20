"""Knowledge retrieval service for the GeoSense RAG explanation layer.

Loads curated environmental and city-specific knowledge from a local JSONL corpus.
Retrieves knowledge items based on the data present in the validated evidence object
and the specified city.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

KNOWLEDGE_FILE = Path(__file__).parent / "rag_knowledge.jsonl"


def _load_corpus() -> List[Dict[str, Any]]:
    """Load the JSONL knowledge corpus from disk."""
    if not KNOWLEDGE_FILE.exists():
        return []

    corpus = []
    with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                corpus.append(item)
            except json.JSONDecodeError:
                continue
    return corpus


def get_knowledge_context(evidence: dict[str, Any], city: str = "Mumbai") -> List[Dict[str, Any]]:
    """Retrieve relevant knowledge items for the given evidence and city.

    Selection logic:
    - Always include global (city=None) or matching city items IF their category
      is relevant to the current evidence.
    - If evidence has non-null AQI, include 'aqi' category.
    - If evidence has non-null NDVI, include 'ndvi' category.
    - If evidence has non-null NDWI, include 'ndwi' category.
    - If evidence has non-null Water Health evidence, include 'water_health' category.
    - If evidence has non-null LST, include 'lst' category.
    - If evidence is an anomaly, include 'anomaly' category.
    - 'climate' or general categories are included based on city match.
    """
    corpus = _load_corpus()
    if not corpus:
        return []

    # Determine what data is available in the evidence
    measurements = evidence.get("measurements", {})
    iso_forest = evidence.get("isolation_forest", {})

    has_aqi = measurements.get("aqi") is not None
    has_ndvi = measurements.get("ndvi") is not None
    has_ndwi = measurements.get("ndwi") is not None
    has_water_health = any(
        measurements.get(field) is not None
        for field in ("mndwi", "ndci", "turbidity_proxy", "water_extent_m2", "water_health_score")
    )
    has_lst = measurements.get("lst") is not None
    is_anomaly = iso_forest.get("is_anomaly") is True

    selected_knowledge = []

    for item in corpus:
        item_city = item.get("city")
        # City filter: must be global (None) or match the requested city (case-insensitive)
        if item_city is not None and item_city.lower() != city.lower():
            continue

        category = item.get("category")
        
        # Category filter rules based on evidence
        include = False
        if category == "aqi" and has_aqi:
            include = True
        elif category == "ndvi" and has_ndvi:
            include = True
        elif category == "ndwi" and has_ndwi:
            include = True
        elif category == "water_health" and has_water_health:
            include = True
        elif category == "lst" and has_lst:
            include = True
        elif category == "anomaly" and is_anomaly:
            include = True
        elif category == "climate":
            # Always include climate context for the matched city
            include = True

        if include:
            selected_knowledge.append(item)

    return selected_knowledge
