"""Unit tests for the LLM client."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from typing import Any
import httpx

from app.services.llm_client import (
    call_gemini,
    LLMUnavailable,
    InvalidLLMResponse,
    _build_prompt
)


def _make_evidence() -> dict[str, Any]:
    return {
        "zone": {"id": 1, "name": "Test Zone", "city": "Mumbai"},
        "measurements": {"aqi": 100, "lst": None},
        "isolation_forest": {"is_anomaly": True}
    }


def _make_knowledge() -> list[dict[str, Any]]:
    return [{"knowledge_id": "k1", "title": "T1", "content": "C1"}]


class LLMClientTests(unittest.IsolatedAsyncioTestCase):

    @patch("app.services.llm_client.get_settings")
    async def test_missing_api_key_raises_unavailable(self, mock_settings):
        settings_mock = MagicMock()
        settings_mock.gemini_api_key = None
        mock_settings.return_value = settings_mock

        with self.assertRaises(LLMUnavailable):
            await call_gemini(_make_evidence(), _make_knowledge(), "Deterministic")

    @patch("app.services.llm_client.httpx.AsyncClient")
    @patch("app.services.llm_client.get_settings")
    async def test_timeout_raises_unavailable(self, mock_settings, mock_client_class):
        settings_mock = MagicMock()
        settings_mock.gemini_api_key = "fake_key"
        mock_settings.return_value = settings_mock

        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.TimeoutException("Timeout")
        
        # Mock the context manager __aenter__ to return our mock_client
        mock_client_class.return_value.__aenter__.return_value = mock_client

        with self.assertRaises(LLMUnavailable):
            await call_gemini(_make_evidence(), _make_knowledge(), "Deterministic")

    @patch("app.services.llm_client.httpx.AsyncClient")
    @patch("app.services.llm_client.get_settings")
    async def test_http_error_raises_unavailable(self, mock_settings, mock_client_class):
        settings_mock = MagicMock()
        settings_mock.gemini_api_key = "fake_key"
        mock_settings.return_value = settings_mock

        mock_client = AsyncMock()
        # Create a real response object to raise HTTPStatusError
        request = httpx.Request("POST", "http://test")
        response = httpx.Response(500, request=request)
        mock_client.post.side_effect = httpx.HTTPStatusError("Error", request=request, response=response)
        
        mock_client_class.return_value.__aenter__.return_value = mock_client

        with self.assertRaises(LLMUnavailable):
            await call_gemini(_make_evidence(), _make_knowledge(), "Deterministic")

    @patch("app.services.llm_client.httpx.AsyncClient")
    @patch("app.services.llm_client.get_settings")
    async def test_invalid_json_response_raises_invalid(self, mock_settings, mock_client_class):
        settings_mock = MagicMock()
        settings_mock.gemini_api_key = "fake_key"
        mock_settings.return_value = settings_mock

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "NOT JSON"}]}}]
        }
        mock_client.post.return_value = mock_response
        
        mock_client_class.return_value.__aenter__.return_value = mock_client

        with self.assertRaises(InvalidLLMResponse):
            await call_gemini(_make_evidence(), _make_knowledge(), "Deterministic")

    @patch("app.services.llm_client.httpx.AsyncClient")
    @patch("app.services.llm_client.get_settings")
    async def test_successful_structured_response(self, mock_settings, mock_client_class):
        settings_mock = MagicMock()
        settings_mock.gemini_api_key = "fake_key"
        mock_settings.return_value = settings_mock

        expected_result = {
            "summary": "Summary text",
            "observations_paragraph": "Obs",
            "model_signals_paragraph": "Mod",
            "temporal_paragraph": "Temp",
            "knowledge_context_used": ["k1"],
            "warnings": []
        }

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": json.dumps(expected_result)}]}}]
        }
        mock_client.post.return_value = mock_response
        
        mock_client_class.return_value.__aenter__.return_value = mock_client

        result = await call_gemini(_make_evidence(), _make_knowledge(), "Deterministic")
        self.assertEqual(result, expected_result)

    def test_prompt_contains_evidence_and_rules(self):
        evidence = _make_evidence()
        knowledge = _make_knowledge()
        prompt = _build_prompt(evidence, knowledge, "Det text")
        
        self.assertIn("Mumbai", prompt)
        self.assertIn("100", prompt)  # AQI value
        self.assertIn("k1", prompt)   # Knowledge ID
        self.assertIn("Never invent measurements", prompt)
        self.assertIn("Det text", prompt)
