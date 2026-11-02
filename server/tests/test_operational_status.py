"""Pure tests for operational-status presentation; no database writes."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = REPO_ROOT / "server"
for path in (str(REPO_ROOT), str(SERVER_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from app.services.operational_status import summarize_temporal_readiness


class OperationalStatusTests(unittest.TestCase):
    def test_temporal_readiness_summary_preserves_prior_only_counts(self) -> None:
        result = summarize_temporal_readiness([
            {"metric": "lst", "current_combinations": 189, "at_least_1_prior": 10, "at_least_3_prior": 4, "trend_ready": 4}
        ])
        self.assertEqual(result["lst"]["at_least_1_prior"], 10)
        self.assertEqual(result["lst"]["at_least_3_prior"], 4)
        self.assertEqual(result["lst"]["trend_ready"], 4)

