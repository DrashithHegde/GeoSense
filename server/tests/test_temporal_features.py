"""Pure calculation tests; no synthetic observations are inserted into GeoSense."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = REPO_ROOT / "server"
for path in (str(REPO_ROOT), str(SERVER_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from app.services.temporal_features import (
    calculate_metric_context,
    finalize_anomaly_persistence,
    source_contexts_are_temporally_compatible,
)


def _observation(value: float, day: int, record_id: int) -> dict:
    return {
        "value": value,
        "observed_at": datetime(2026, 8, day, tzinfo=timezone.utc),
        "environment_data_id": record_id,
    }


class TemporalFeatureTests(unittest.TestCase):
    def test_fixed_window_composites_remain_comparable_across_dates(self) -> None:
        current = {
            "dataset": "COPERNICUS/S2_SR_HARMONIZED",
            "window_start": "2026-08-04",
            "window_end": "2026-08-18",
            "window_days": 14,
            "composite": "median",
            "cloud_mask": "QA60 bits 10 and 11",
        }
        prior = {**current, "window_start": "2026-07-28", "window_end": "2026-08-11"}
        self.assertTrue(source_contexts_are_temporally_compatible(current, prior))
        self.assertFalse(source_contexts_are_temporally_compatible(current, {**prior, "window_days": 10}))

    def test_baseline_excludes_current_and_rate_uses_elapsed_days(self) -> None:
        result = calculate_metric_context(
            metric="lst",
            current=_observation(16.0, 10, 4),
            prior_observations=[_observation(10.0, 1, 1), _observation(12.0, 4, 2), _observation(14.0, 7, 3)],
            metadata_context={"window_days": 45},
            aqi_source_type=None,
        )
        self.assertEqual(result["prior_baseline"]["mean"], 12.0)
        self.assertEqual(result["prior_baseline"]["count"], 3)
        self.assertEqual(result["delta"], 2.0)
        self.assertAlmostEqual(result["rate_per_day"], 2.0 / 3.0)
        self.assertAlmostEqual(result["historical_deviation_z_score"], 2.0)
        self.assertEqual(result["trend"]["direction"], "increasing")
        self.assertEqual(result["trend"]["observations_used"], 4)

    def test_insufficient_history_is_explicitly_unavailable(self) -> None:
        result = calculate_metric_context(
            metric="ndvi",
            current=_observation(0.4, 10, 2),
            prior_observations=[_observation(0.3, 1, 1)],
            metadata_context={"window_days": 14},
            aqi_source_type=None,
        )
        self.assertAlmostEqual(result["delta"], 0.1)
        self.assertEqual(result["prior_baseline"]["mean"], None)
        self.assertEqual(result["historical_deviation_z_score"], None)
        self.assertEqual(result["trend"]["slope_per_day"], None)
        self.assertEqual(result["unavailable_reason"], "insufficient_compatible_history_for_baseline")

    def test_persistence_requires_prior_spatial_snapshots(self) -> None:
        unavailable = finalize_anomaly_persistence(
            {"availability": False, "unavailable_reason": "insufficient_prior_spatial_anomaly_history"},
            True,
        )
        self.assertEqual(unavailable["classification"], "unavailable")
        persistent = finalize_anomaly_persistence(
            {"availability": True, "prior_anomaly_streak": 2, "unavailable_reason": None},
            True,
        )
        self.assertEqual(persistent["current_anomaly_streak"], 3)
        self.assertEqual(persistent["classification"], "persistent")
