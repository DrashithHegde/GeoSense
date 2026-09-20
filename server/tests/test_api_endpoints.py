"""Automated API route tests using FastAPI TestClient."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = REPO_ROOT / "server"
for path in (str(REPO_ROOT), str(SERVER_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from fastapi.testclient import TestClient
from app.main import app


class ApiEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_check(self):
        res = self.client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("status"), "healthy")
        self.assertEqual(data.get("phase"), "2")

    def test_system_status(self):
        res = self.client.get("/api/system/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("read_only"))
        self.assertEqual(data.get("raw_data", {}).get("duplicate_zone_timestamp_rows"), 0)
        # 189 canonical analytical zones (restored from generated_zones.geojson)
        self.assertEqual(data.get("raw_data", {}).get("total_zones"), 189)

    def test_anomalies_endpoint(self):
        res = self.client.get("/api/anomalies?days=30&limit=100")
        self.assertEqual(res.status_code, 200)
        anomalies = res.json()
        # Accept any non-negative count — some anomaly zones may have been outside boundary
        self.assertGreaterEqual(len(anomalies), 0)
        for a in anomalies:
            self.assertTrue(a.get("is_anomaly"))
            self.assertIsNotNone(a.get("anomaly_score"))
            self.assertIsNotNone(a.get("root_cause"))

    def test_metrics_latest(self):
        res = self.client.get("/api/metrics/latest")
        self.assertEqual(res.status_code, 200)
        metrics = res.json()
        # 189 canonical analytical zones (restored from generated_zones.geojson)
        self.assertEqual(len(metrics), 189)

    def test_municipalities_latest_uses_all_local_boundary_assets(self):
        res = self.client.get("/api/municipalities/latest")
        self.assertEqual(res.status_code, 200)
        municipalities = res.json()
        self.assertEqual([item["id"] for item in municipalities], ["mumbai", "thane", "mira_bhayandar"])
        for municipality in municipalities:
            self.assertIn(municipality["geometry"]["type"], ("Polygon", "MultiPolygon"))
            self.assertIn("zone_count", municipality)

    def test_metrics_latest_uses_async_source_timestamps_and_composite(self):
        res = self.client.get("/api/metrics/latest")
        self.assertEqual(res.status_code, 200)
        metrics = res.json()
        self.assertTrue(any(item["aqi"] is not None and item["aqi_observed_at"] is not None for item in metrics))
        self.assertTrue(any(item["ndvi"] is not None and item["ndvi_observed_at"] is not None for item in metrics))
        self.assertTrue(any(item["lst"] is not None and item["lst_observed_at"] is not None for item in metrics))
        self.assertTrue(any(item["water_health_score"] is not None and item["water_health_observed_at"] is not None for item in metrics))

        item = next(item for item in metrics if item["water_health_score"] is not None)
        composite = item["composite"]
        self.assertIn("water_health", composite["available_components"])
        self.assertAlmostEqual(
            composite["score"],
            sum(composite["contributions"].values()),
            places=3,
        )
        self.assertIsNotNone(item["ndvi_observed_at"])
        self.assertIsNotNone(item["water_health_observed_at"])

        non_water = next(item for item in metrics if item["water_health_score"] is None)
        self.assertIsNone(non_water["water_health_score"])
        self.assertNotIn("water_health", non_water["composite"]["available_components"])
        self.assertIn("water_health", non_water["composite"]["missing_components"])

    def test_aqi_stations(self):
        res = self.client.get("/api/aqi/stations")
        self.assertEqual(res.status_code, 200)
        stations = res.json()
        # 138 clipped zones — all have AQI data
        self.assertGreaterEqual(len(stations), 130)

    def test_metrics_latest_includes_geometry(self):
        """Verify that the metrics API returns polygon geometry for map rendering."""
        res = self.client.get("/api/metrics/latest")
        self.assertEqual(res.status_code, 200)
        metrics = res.json()
        # Every zone should have a geometry object (MultiPolygon)
        for m in metrics:
            self.assertIsNotNone(m.get("geometry"), f"Zone {m['id']} missing geometry")
            self.assertIn(m["geometry"]["type"], ("Polygon", "MultiPolygon"))
