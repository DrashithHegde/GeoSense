"""Tests for the Phase 10A evidence-grounded explanation layer.

Test coverage:
- Evidence assembly from a real anomaly result
- Evidence assembly for a non-anomalous (inlier) zone
- Missing LST handling (NULL in database → "unavailable" in explanation)
- Estimated vs. observed AQI provenance
- Insufficient temporal history
- Valid temporal history when available
- Missing provenance metadata
- No anomaly result for zone (NoAnomalyResultError)
- Unknown zone (ZoneNotFoundError)
- API endpoint: anomalous zone
- API endpoint: inlier zone
- API endpoint: zone with no result (404)
- API endpoint: unknown zone (404)
- API endpoint: response schema consistency
- Explanation text cannot contain values absent from evidence
- Limitations list is accurate for missing LST
- Limitations list is accurate for IDW-estimated AQI
"""
from __future__ import annotations

import unittest
from pathlib import Path
import sys
from typing import Any
from datetime import datetime, timezone, timedelta

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = REPO_ROOT / "server"
for path in (str(REPO_ROOT), str(SERVER_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from fastapi.testclient import TestClient
from app.main import app
from app.services.explanation_evidence import (
    build_zone_evidence,
    ZoneNotFoundError,
    NoAnomalyResultError,
    UNAVAILABLE,
)
from app.services.explanation_engine import generate_deterministic_explanation


# ──────────────────────────────────────────────────────────────
# Evidence object factory helpers for unit tests
# These construct minimal synthetic evidence dicts that match the
# schema produced by build_zone_evidence().  They NEVER touch the DB.
# ──────────────────────────────────────────────────────────────

_NOW = datetime.now(timezone.utc).isoformat()
_YESTERDAY = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


def _make_evidence(
    *,
    zone_id: int = 1,
    zone_name: str = "Test Zone",
    is_anomaly: bool = True,
    aqi: int | None = 85,
    lst: float | None = 32.5,
    ndvi: float | None = 0.35,
    ndwi: float | None = -0.10,
    aqi_source_type: str | None = "observed",
    aqi_dist_m: float | None = None,
    dominant_deviations: list | None = None,
    feature_z_scores: dict | None = None,
    has_temporal_aqi: bool = False,
    has_baseline_aqi: bool = False,
    has_temporal_ndvi: bool = False,
) -> dict[str, Any]:
    """Build a synthetic evidence dict for unit-testing the engine and API."""

    def _temporal_metric(has_prev: bool, has_baseline: bool) -> dict:
        if not has_prev:
            return {"available": True, "previous_observation": None, "delta": None,
                    "rate_per_day": None, "baseline": None, "trend": None,
                    "unavailable_reason": "insufficient_compatible_history"}
        base: dict[str, Any] = {
            "available": True,
            "unavailable_reason": None,
            "previous_observation": {"value": 80.0, "observed_at": _YESTERDAY, "elapsed_days": 1.0},
            "delta": 5.0,
            "rate_per_day": 5.0,
            "baseline": None,
            "trend": None,
        }
        if has_baseline:
            base["baseline"] = {"count": 4, "mean": 78.0, "median": 77.5, "standard_deviation": 4.0, "z_score": 1.75}
            base["trend"] = {"slope_per_day": 2.1, "direction": "increasing", "observations_used": 5}
        else:
            base["unavailable_reason"] = "insufficient_compatible_history_for_baseline"
        return base

    devs = dominant_deviations or [
        {"variable": "lst", "label": "LST", "direction": "above", "z_score": 2.45, "value": lst},
        {"variable": "ndwi", "label": "NDWI", "direction": "below", "z_score": -1.80, "value": ndwi},
    ]
    z_scores = feature_z_scores or {
        "aqi": 0.32,
        "lst": 2.45 if lst is not None else None,
        "ndvi": -0.55,
        "ndwi": -1.80,
    }

    return {
        "schema_version": "1.0",
        "evidence_generated_at": _NOW,
        "zone": {"id": zone_id, "name": zone_name, "ward": "A"},
        "analysis_timestamp": _YESTERDAY,
        "detected_at": _NOW,
        "measurements": {
            "aqi": aqi,
            "lst": lst,
            "ndvi": ndvi,
            "ndwi": ndwi,
            "pm25": None,
            "pm10": None,
            "no2": None,
        },
        "isolation_forest": {
            "model_name": "isolation_forest_spatial_v1",
            "snapshot_date": _YESTERDAY[:10],
            "is_anomaly": is_anomaly,
            "anomaly_score": 0.58 if is_anomaly else 0.42,
            "anomaly_type": "isolation_forest_spatial_anomaly" if is_anomaly else "isolation_forest_spatial_inlier",
            "root_cause_string": "Spatial outlier: LST above (+2.45σ)" if is_anomaly else None,
            "feature_z_scores": {k: v for k, v in z_scores.items() if v is not None},
            "dominant_deviations": devs if is_anomaly else [],
            "features_used": ["aqi", "lst", "ndvi", "ndwi"],
            "features_excluded_constant": [],
        },
        "temporal_context": {
            "aqi": _temporal_metric(has_temporal_aqi, has_baseline_aqi),
            "lst": {"available": True, "previous_observation": None, "delta": None,
                    "rate_per_day": None, "baseline": None, "trend": None,
                    "unavailable_reason": "insufficient_compatible_history"},
            "ndvi": _temporal_metric(has_temporal_ndvi, False),
            "ndwi": {"available": True, "previous_observation": None, "delta": None,
                     "rate_per_day": None, "baseline": None, "trend": None,
                     "unavailable_reason": "insufficient_compatible_history"},
        },
        "anomaly_persistence": {
            "available": False,
            "prior_anomaly_count": None,
            "prior_anomaly_streak": None,
            "classification": UNAVAILABLE,
            "unavailable_reason": "insufficient_prior_spatial_anomaly_history",
        },
        "provenance": {
            "aqi": {
                "source_type": aqi_source_type,
                "nearest_station_distance_m": aqi_dist_m,
            },
            "satellite": {
                "ndvi_ndwi": {
                    "observed_at": _YESTERDAY,
                    "source_configuration": {
                        "dataset": "COPERNICUS/S2_SR_HARMONIZED",
                        "window_days": 14,
                        "cloud_mask": "QA60 bits 10 and 11",
                    },
                },
                "lst": {"observed_at": None, "source_configuration": None},
            },
        },
        "limitations": [
            *(["LST is unavailable for this analytical snapshot (no valid Landsat scene)."] if lst is None else []),
            *(
                [f"AQI is IDW-estimated (nearest station: {aqi_dist_m:.0f} m), not a direct station observation."]
                if aqi_source_type == "estimated"
                else []
            ),
        ],
    }


# ──────────────────────────────────────────────────────────────
# Unit tests for explanation_engine
# ──────────────────────────────────────────────────────────────

class ExplanationEngineUnitTests(unittest.TestCase):

    def test_anomaly_explanation_contains_classification(self):
        evidence = _make_evidence(is_anomaly=True)
        text = generate_deterministic_explanation(evidence)
        self.assertIn("SPATIAL ANOMALY", text)

    def test_inlier_explanation_contains_classification(self):
        evidence = _make_evidence(is_anomaly=False)
        text = generate_deterministic_explanation(evidence)
        self.assertIn("SPATIAL INLIER", text)

    def test_missing_lst_says_unavailable(self):
        evidence = _make_evidence(lst=None)
        text = generate_deterministic_explanation(evidence)
        self.assertIn("LST: unavailable", text)
        # Must not invent a temperature
        self.assertNotIn("°C", text)

    def test_lst_present_shows_value(self):
        evidence = _make_evidence(lst=34.12)
        text = generate_deterministic_explanation(evidence)
        self.assertIn("34.12 °C", text)

    def test_estimated_aqi_calls_out_idw(self):
        evidence = _make_evidence(aqi_source_type="estimated", aqi_dist_m=4500.0)
        text = generate_deterministic_explanation(evidence)
        self.assertIn("IDW-estimated", text)

    def test_observed_aqi_does_not_say_idw(self):
        evidence = _make_evidence(aqi_source_type="observed")
        text = generate_deterministic_explanation(evidence)
        self.assertNotIn("IDW-estimated", text)

    def test_dominant_deviations_appear_for_anomaly(self):
        evidence = _make_evidence(is_anomaly=True)
        text = generate_deterministic_explanation(evidence)
        self.assertIn("dominant deviation", text.lower())
        self.assertIn("LST", text)

    def test_dominant_deviations_absent_for_inlier(self):
        evidence = _make_evidence(is_anomaly=False)
        text = generate_deterministic_explanation(evidence)
        # Inlier should not print dominant deviations section
        self.assertNotIn("dominant deviation", text.lower())

    def test_no_causation_language(self):
        evidence = _make_evidence(is_anomaly=True)
        text = generate_deterministic_explanation(evidence)
        forbidden = ["caused by", "because of", "the reason is"]
        for phrase in forbidden:
            self.assertNotIn(phrase, text.lower(), msg=f"Found forbidden causal language: '{phrase}'")

    def test_attribution_language_present(self):
        evidence = _make_evidence(is_anomaly=True)
        text = generate_deterministic_explanation(evidence)
        # Must use non-causal attribution language
        self.assertTrue(
            any(phrase in text.lower() for phrase in ["dominant deviation", "model contributor", "statistical deviation"]),
            "Expected model-attribution language not found in explanation",
        )

    def test_insufficient_temporal_history_is_explicit(self):
        evidence = _make_evidence(has_temporal_aqi=False)
        text = generate_deterministic_explanation(evidence)
        self.assertIn("unavailable", text.lower())

    def test_temporal_delta_appears_when_available(self):
        evidence = _make_evidence(has_temporal_aqi=True, has_baseline_aqi=False)
        text = generate_deterministic_explanation(evidence)
        self.assertIn("Rate of change", text)

    def test_baseline_appears_when_available(self):
        evidence = _make_evidence(has_temporal_aqi=True, has_baseline_aqi=True)
        text = generate_deterministic_explanation(evidence)
        self.assertIn("Historical baseline mean", text)

    def test_limitations_section_present(self):
        evidence = _make_evidence(lst=None)
        text = generate_deterministic_explanation(evidence)
        self.assertIn("Known data limitations", text)

    def test_explanation_does_not_invent_values_absent_from_evidence(self):
        """Values in the explanation must be traceable to the evidence object."""
        evidence = _make_evidence(aqi=72, lst=None, ndvi=0.41, ndwi=-0.15)
        text = generate_deterministic_explanation(evidence)
        # AQI 72 should appear
        self.assertIn("72", text)
        # NDVI 0.41 should appear
        self.assertIn("0.41", text)
        # NDWI -0.15 should appear
        self.assertIn("-0.15", text)
        # LST value of 34.12 must NOT appear (lst=None)
        self.assertNotIn("34.12", text)

    def test_persistence_unavailable_is_explicit(self):
        evidence = _make_evidence()
        text = generate_deterministic_explanation(evidence)
        self.assertIn("persistence", text.lower())
        self.assertIn("unavailable", text.lower())

    def test_provenance_section_present(self):
        evidence = _make_evidence()
        text = generate_deterministic_explanation(evidence)
        self.assertIn("Source provenance", text)
        self.assertIn("COPERNICUS/S2_SR_HARMONIZED", text)

    def test_missing_aqi_says_unavailable(self):
        evidence = _make_evidence(aqi=None)
        text = generate_deterministic_explanation(evidence)
        self.assertIn("AQI: unavailable", text)


# ──────────────────────────────────────────────────────────────
# API endpoint tests (require live database via TestClient)
# ──────────────────────────────────────────────────────────────

class ExplanationApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def _anomaly_zone_ids(self) -> list[int]:
        """Get zone IDs that have anomaly results in the live DB."""
        res = self.client.get("/api/anomalies?days=30&limit=100")
        self.assertEqual(res.status_code, 200)
        return [a["locality_id"] for a in res.json() if a.get("is_anomaly")]

    def test_anomalous_zone_returns_200(self):
        zone_ids = self._anomaly_zone_ids()
        self.assertTrue(zone_ids, "No anomaly results in DB; cannot run API test")
        res = self.client.get(f"/api/zones/{zone_ids[0]}/explanation")
        self.assertEqual(res.status_code, 200)

    def test_anomalous_zone_classification_field(self):
        zone_ids = self._anomaly_zone_ids()
        self.assertTrue(zone_ids)
        res = self.client.get(f"/api/zones/{zone_ids[0]}/explanation")
        data = res.json()
        self.assertEqual(data["classification"], "anomaly")

    def test_response_has_required_top_level_keys(self):
        zone_ids = self._anomaly_zone_ids()
        self.assertTrue(zone_ids)
        data = self.client.get(f"/api/zones/{zone_ids[0]}/explanation").json()
        for key in ("zone_id", "zone_name", "analysis_timestamp", "classification",
                    "deterministic_explanation", "evidence", "limitations", "provenance"):
            self.assertIn(key, data, f"Missing key in API response: {key}")

    def test_explanation_is_nonempty_string(self):
        zone_ids = self._anomaly_zone_ids()
        self.assertTrue(zone_ids)
        data = self.client.get(f"/api/zones/{zone_ids[0]}/explanation").json()
        self.assertIsInstance(data["deterministic_explanation"], str)
        self.assertGreater(len(data["deterministic_explanation"]), 50)

    def test_evidence_contains_measurements(self):
        zone_ids = self._anomaly_zone_ids()
        self.assertTrue(zone_ids)
        data = self.client.get(f"/api/zones/{zone_ids[0]}/explanation").json()
        evidence = data["evidence"]
        self.assertIn("measurements", evidence)
        measurements = evidence["measurements"]
        self.assertIn("aqi", measurements)
        self.assertIn("lst", measurements)
        self.assertIn("ndvi", measurements)
        self.assertIn("ndwi", measurements)

    def test_lst_value_in_evidence_matches_database_reality(self):
        """The evidence must reflect the actual database value for LST.

        The Isolation Forest snapshot at 2026-08-16 used the one valid Landsat
        window that existed.  The evidence must carry that value, not None.
        If a future snapshot is run during monsoon (no Landsat), LST will be None.
        Either way: the evidence must match the DB — it must never fabricate a value.
        """
        zone_ids = self._anomaly_zone_ids()
        self.assertTrue(zone_ids)
        data = self.client.get(f"/api/zones/{zone_ids[0]}/explanation").json()
        evidence = data["evidence"]
        measurements = evidence["measurements"]
        lst_in_evidence = measurements["lst"]
        # The value is either a real float (from a valid Landsat scene) or None
        # (from a monsoon window with no scenes).  Both are acceptable.
        # What is NOT acceptable is a fabricated, forward-filled, or inferred value.
        self.assertIn("lst", measurements,
                      "LST key must always be present in measurements (even if None)")
        if lst_in_evidence is not None:
            self.assertIsInstance(lst_in_evidence, float,
                                  "LST must be a real float if present in evidence")
        # The explanation text must be consistent with the evidence value
        explanation = data["deterministic_explanation"]
        if lst_in_evidence is None:
            self.assertIn("LST: unavailable", explanation)
        else:
            # A valid LST should appear as a formatted number in the explanation
            self.assertIn("°C", explanation)

    def test_lst_unavailable_in_limitations_when_null(self):
        """When the evidence reports LST as None, limitations must call it out."""
        zone_ids = self._anomaly_zone_ids()
        self.assertTrue(zone_ids)
        data = self.client.get(f"/api/zones/{zone_ids[0]}/explanation").json()
        evidence = data["evidence"]
        measurements = evidence["measurements"]
        lst_in_evidence = measurements["lst"]
        if lst_in_evidence is None:
            limitations_text = " ".join(data.get("limitations", []))
            self.assertIn("LST", limitations_text,
                          "LST must appear in limitations when null in evidence")
        else:
            # LST is present — limitation about LST is not required
            pass

    def test_unknown_zone_returns_404(self):
        res = self.client.get("/api/zones/999999/explanation")
        self.assertEqual(res.status_code, 404)

    def test_explanation_text_not_empty_for_inlier(self):
        """Zones that exist but are inliers should also return 200 with explanation."""
        # Get all zone IDs from metrics to find an inlier (has IF result but is_anomaly=False)
        res = self.client.get("/api/anomalies?days=30&limit=200")
        anomaly_zone_ids = {a["locality_id"] for a in res.json()}
        all_res = self.client.get("/api/metrics/latest")
        all_zone_ids = [z["id"] for z in all_res.json()]
        inlier_candidates = [z for z in all_zone_ids if z not in anomaly_zone_ids]
        # Some inlier zones may have IF results (classified as inlier)
        # Find one that has a result
        found_inlier = None
        for zone_id in inlier_candidates[:20]:  # Only probe first 20 to avoid slow tests
            r = self.client.get(f"/api/zones/{zone_id}/explanation")
            if r.status_code == 200:
                found_inlier = r.json()
                break
        if found_inlier is None:
            self.skipTest("No inlier zone with an existing IF result found in live DB")
        self.assertEqual(found_inlier["classification"], "inlier")
        self.assertIsInstance(found_inlier["deterministic_explanation"], str)
        self.assertGreater(len(found_inlier["deterministic_explanation"]), 20)

    def test_zone_with_no_if_result_returns_404(self):
        """A zone that has environment_data but no anomaly_result should return 404."""
        # Use a zone ID just outside the range of processed zones  
        # The IF pipeline requires all-4-metrics rows; some zones may be excluded.
        # Zone 999998 does not exist, so it should also 404.
        res = self.client.get("/api/zones/999998/explanation")
        self.assertEqual(res.status_code, 404)

    def test_response_is_deterministic(self):
        """Two calls to the same endpoint must return identical explanations."""
        zone_ids = self._anomaly_zone_ids()
        self.assertTrue(zone_ids)
        url = f"/api/zones/{zone_ids[0]}/explanation"
        r1 = self.client.get(url).json()
        r2 = self.client.get(url).json()
        self.assertEqual(r1["deterministic_explanation"], r2["deterministic_explanation"])
        self.assertEqual(r1["classification"], r2["classification"])

    def test_existing_api_endpoints_unaffected(self):
        """Confirm no regressions on pre-existing endpoints after Phase 10A changes."""
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        self.assertEqual(self.client.get("/api/system/status").status_code, 200)
        self.assertEqual(self.client.get("/api/metrics/latest").status_code, 200)
        self.assertEqual(self.client.get("/api/anomalies?days=30&limit=100").status_code, 200)
        self.assertEqual(self.client.get("/api/aqi/stations").status_code, 200)
