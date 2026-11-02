"""Unit tests for the knowledge retrieval layer."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch
from typing import Any

from app.services.rag_knowledge import get_knowledge_context, _load_corpus


# Minimal evidence factory for testing
def _make_evidence(
    aqi: int | None = 100,
    lst: float | None = 30.0,
    ndvi: float | None = 0.5,
    ndwi: float | None = 0.1,
    is_anomaly: bool = False
) -> dict[str, Any]:
    return {
        "measurements": {
            "aqi": aqi,
            "lst": lst,
            "ndvi": ndvi,
            "ndwi": ndwi,
        },
        "isolation_forest": {
            "is_anomaly": is_anomaly
        }
    }


class RagKnowledgeTests(unittest.TestCase):

    def test_corpus_loads_valid_jsonl(self):
        corpus = _load_corpus()
        self.assertGreater(len(corpus), 0, "Corpus should not be empty")
        for item in corpus:
            self.assertIn("knowledge_id", item)
            self.assertIn("title", item)
            self.assertIn("content", item)
            self.assertIn("category", item)
            self.assertIn("city", item)

    def test_global_knowledge_included_when_metric_present(self):
        evidence = _make_evidence(aqi=100, lst=None, ndvi=None, ndwi=None)
        context = get_knowledge_context(evidence, city="Mumbai")
        ids = [item["knowledge_id"] for item in context]
        self.assertIn("aqi_cpcb_scale", ids)
        self.assertNotIn("lst_urban_heat", ids)
        self.assertNotIn("ndvi_interpretation", ids)

    def test_metric_knowledge_excluded_when_metric_missing(self):
        evidence = _make_evidence(lst=None)
        context = get_knowledge_context(evidence, city="Mumbai")
        ids = [item["knowledge_id"] for item in context]
        self.assertNotIn("lst_urban_heat", ids)

    def test_anomaly_knowledge_included_only_when_anomaly(self):
        evidence_inlier = _make_evidence(is_anomaly=False)
        context_inlier = get_knowledge_context(evidence_inlier, city="Mumbai")
        self.assertNotIn("isolation_forest_explanation", [item["knowledge_id"] for item in context_inlier])

        evidence_anomaly = _make_evidence(is_anomaly=True)
        context_anomaly = get_knowledge_context(evidence_anomaly, city="Mumbai")
        self.assertIn("isolation_forest_explanation", [item["knowledge_id"] for item in context_anomaly])

    def test_city_specific_knowledge(self):
        # Mumbai context included for Mumbai
        evidence = _make_evidence()
        context_mumbai = get_knowledge_context(evidence, city="Mumbai")
        ids_mumbai = [item["knowledge_id"] for item in context_mumbai]
        self.assertIn("mumbai_monsoon_context", ids_mumbai)

        # Mumbai context excluded for Bengaluru
        context_bengaluru = get_knowledge_context(evidence, city="Bengaluru")
        ids_bengaluru = [item["knowledge_id"] for item in context_bengaluru]
        self.assertNotIn("mumbai_monsoon_context", ids_bengaluru)

    @patch("app.services.rag_knowledge.KNOWLEDGE_FILE")
    def test_missing_corpus_file_returns_empty_list(self, mock_file):
        mock_file.exists.return_value = False
        evidence = _make_evidence()
        context = get_knowledge_context(evidence, city="Mumbai")
        self.assertEqual(context, [])
