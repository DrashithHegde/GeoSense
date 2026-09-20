"""Pure scheduler gating tests; no external ingestion or database writes."""
from __future__ import annotations

from datetime import date
from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = REPO_ROOT / "server"
for path in (str(REPO_ROOT), str(SERVER_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from scripts.scheduler import should_run_feature_pipeline


class SchedulerFeatureGateTests(unittest.TestCase):
    def test_requires_same_day_success_for_all_sources(self) -> None:
        today = date(2026, 8, 18)
        self.assertFalse(
            should_run_feature_pipeline(
                today=today,
                satellite_ready_date=today,
                aqi_ready_date=None,
                analysis_completed_date=None,
                source_completed_this_cycle=True,
            )
        )
        self.assertTrue(
            should_run_feature_pipeline(
                today=today,
                satellite_ready_date=today,
                aqi_ready_date=today,
                analysis_completed_date=None,
                source_completed_this_cycle=True,
            )
        )

    def test_later_aqi_success_can_finish_pending_satellite_snapshot_once(self) -> None:
        today = date(2026, 8, 18)
        self.assertTrue(
            should_run_feature_pipeline(
                today=today,
                satellite_ready_date=today,
                aqi_ready_date=today,
                analysis_completed_date=None,
                source_completed_this_cycle=True,
            )
        )
        self.assertFalse(
            should_run_feature_pipeline(
                today=today,
                satellite_ready_date=today,
                aqi_ready_date=today,
                analysis_completed_date=today,
                source_completed_this_cycle=True,
            )
        )

