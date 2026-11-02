"""Unit tests for the explanation service orchestrator."""
from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock, AsyncMock
from typing import Any

from app.services.explanation_service import build_full_explanation, _validate_llm_explanation
from app.services.llm_client import LLMUnavailable, InvalidLLMResponse


def _make_evidence(lst: float | None = 30.0) -> dict[str, Any]:
    return {
        "zone": {"id": 1, "name": "Test Zone", "city": "Mumbai"},
        "measurements": {"aqi": 100, "lst": lst},
        "isolation_forest": {"is_anomaly": True},
        "analysis_timestamp": "2026-08-16T00:00:00Z"
    }


class ExplanationServiceTests(unittest.IsolatedAsyncioTestCase):

    def test_validation_passes_valid_llm_output(self):
        llm_expl = {
            "observations_paragraph": "LST is 30.0. AQI is 100."
        }
        evidence = _make_evidence(lst=30.0)
        warnings = _validate_llm_explanation(llm_expl, evidence)
        self.assertEqual(len(warnings), 0)

    def test_validation_warns_on_hallucinated_lst(self):
        llm_expl = {
            "observations_paragraph": "LST is 35.0 °C." # Mentions LST but not unavailable
        }
        evidence = _make_evidence(lst=None) # LST is null in evidence
        warnings = _validate_llm_explanation(llm_expl, evidence)
        self.assertEqual(len(warnings), 1)
        self.assertIn("LST is null in evidence", warnings[0])

    def test_validation_warns_on_forbidden_causal_language(self):
        llm_expl = {
            "observations_paragraph": "This was caused by urban heat."
        }
        evidence = _make_evidence()
        warnings = _validate_llm_explanation(llm_expl, evidence)
        self.assertEqual(len(warnings), 1)
        self.assertIn("forbidden causal language", warnings[0])

    @patch("app.services.explanation_service.build_zone_evidence")
    @patch("app.services.explanation_service.generate_deterministic_explanation")
    @patch("app.services.explanation_service.get_knowledge_context")
    @patch("app.services.explanation_service.generate_llm_explanation")
    async def test_successful_orchestration(self, mock_llm, mock_knowledge, mock_det, mock_build_ev):
        mock_build_ev.return_value = _make_evidence()
        mock_det.return_value = "Det text"
        mock_knowledge.return_value = [{"id": "k1"}]
        mock_llm.return_value = {"observations_paragraph": "Valid text."}

        # Passing a dummy string as db since it's mocked
        result = await build_full_explanation("dummy_db", 1)

        self.assertEqual(result["generation_status"], "llm_success")
        self.assertEqual(result["deterministic_explanation"], "Det text")
        self.assertIn("llm_explanation", result)
        self.assertEqual(result["llm_explanation"]["observations_paragraph"], "Valid text.")

    @patch("app.services.explanation_service.build_zone_evidence")
    @patch("app.services.explanation_service.generate_deterministic_explanation")
    @patch("app.services.explanation_service.get_knowledge_context")
    @patch("app.services.explanation_service.generate_llm_explanation")
    async def test_llm_rejected_due_to_causal_language(self, mock_llm, mock_knowledge, mock_det, mock_build_ev):
        mock_build_ev.return_value = _make_evidence()
        mock_det.return_value = "Det text"
        mock_knowledge.return_value = []
        mock_llm.return_value = {"observations_paragraph": "The anomaly was caused by heat."}

        result = await build_full_explanation("dummy_db", 1)

        self.assertEqual(result["generation_status"], "llm_validation_failed")
        self.assertNotIn("llm_explanation", result)
        self.assertTrue(any("rejected due to failed validation constraints" in w for w in result["warnings"]))

    @patch("app.services.explanation_service.build_zone_evidence")
    @patch("app.services.explanation_service.generate_deterministic_explanation")
    @patch("app.services.explanation_service.get_knowledge_context")
    @patch("app.services.explanation_service.generate_llm_explanation")
    async def test_llm_rejected_due_to_numerical_hallucination(self, mock_llm, mock_knowledge, mock_det, mock_build_ev):
        mock_build_ev.return_value = _make_evidence(lst=None)
        mock_det.return_value = "Det text"
        mock_knowledge.return_value = []
        mock_llm.return_value = {"observations_paragraph": "The LST is 45.2."}

        result = await build_full_explanation("dummy_db", 1)

        self.assertEqual(result["generation_status"], "llm_validation_failed")
        self.assertNotIn("llm_explanation", result)
        self.assertTrue(any("hallucination" in w for w in result["warnings"]))

    @patch("app.services.explanation_service.build_zone_evidence")
    @patch("app.services.explanation_service.generate_deterministic_explanation")
    @patch("app.services.explanation_service.get_knowledge_context")
    @patch("app.services.explanation_service.generate_llm_explanation")
    async def test_llm_unavailable_missing_key(self, mock_llm, mock_knowledge, mock_det, mock_build_ev):
        mock_build_ev.return_value = _make_evidence()
        mock_det.return_value = "Det text"
        mock_knowledge.return_value = []
        mock_llm.side_effect = LLMUnavailable("GEMINI_API_KEY is not configured.")

        result = await build_full_explanation("dummy_db", 1)

        self.assertEqual(result["generation_status"], "llm_not_configured")
        self.assertNotIn("llm_explanation", result)
        self.assertEqual(result["deterministic_explanation"], "Det text")

    @patch("app.services.explanation_service.build_zone_evidence")
    @patch("app.services.explanation_service.generate_deterministic_explanation")
    @patch("app.services.explanation_service.get_knowledge_context")
    @patch("app.services.explanation_service.generate_llm_explanation")
    async def test_llm_returns_invalid_response(self, mock_llm, mock_knowledge, mock_det, mock_build_ev):
        mock_build_ev.return_value = _make_evidence()
        mock_det.return_value = "Det text"
        mock_knowledge.return_value = []
        mock_llm.side_effect = InvalidLLMResponse("Malformed JSON")

        result = await build_full_explanation("dummy_db", 1)

        self.assertEqual(result["generation_status"], "llm_validation_failed")
        self.assertNotIn("llm_explanation", result)
