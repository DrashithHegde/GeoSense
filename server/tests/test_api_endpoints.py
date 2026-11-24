"""API route tests (FastAPI TestClient). Database-backed tests skip when no database is reachable."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def _db_ok() -> bool:
    try:
        from app.database import test_database_connection
        test_database_connection()
        return True
    except Exception:
        return False


DB = _db_ok()
needs_db = unittest.skipUnless(DB, "no database reachable")


class ApiEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_reports_database_state(self):
        data = self.client.get("/api/health").json()
        self.assertEqual(data["status"], "healthy")
        self.assertIn(data["database"], ("ok", "unreachable"))

    def test_cities_lists_all_three(self):
        data = self.client.get("/api/cities").json()
        ids = [c["id"] for c in data["cities"]]
        self.assertEqual(ids, ["mumbai", "delhi", "bengaluru"])
        for c in data["cities"]:
            self.assertTrue(c["boundaries"], c["id"])
            self.assertEqual(len(c["center"]), 2)

    def test_unknown_city_is_404(self):
        res = self.client.get("/api/zones/boundary?city=atlantis")
        self.assertEqual(res.status_code, 404)

    def test_boundary_per_city(self):
        for cid, (lon, lat) in {"mumbai": (72.88, 19.08), "delhi": (77.21, 28.61), "bengaluru": (77.59, 12.97)}.items():
            data = self.client.get(f"/api/zones/boundary?city={cid}").json()
            self.assertEqual(data["properties"]["city"], cid)
            self.assertIn(data["geometry"]["type"], ("Polygon", "MultiPolygon"))
            from shapely.geometry import Point, shape
            self.assertTrue(shape(data["geometry"]).contains(Point(lon, lat)), cid)

    def test_point_decides_the_city(self):
        """?lon=&lat= inside Delhi is answered for Delhi even when ?city= says Mumbai."""
        from app.core.cities import city_for_point
        self.assertEqual(city_for_point(77.21, 28.61), "delhi")
        self.assertEqual(city_for_point(77.59, 12.97), "bengaluru")
        self.assertEqual(city_for_point(72.88, 19.08), "mumbai")
        self.assertIsNone(city_for_point(80.27, 13.08))   # Chennai: not a GeoSense city

    def test_surface_urls_are_per_city(self):
        res = self.client.get("/api/surfaces/lst/latest?city=mumbai")
        if res.status_code == 404:
            self.skipTest("no Mumbai LST surface in this checkout")
        self.assertTrue(res.json()["sharp_url"].startswith("/surface-assets/mumbai/"))

    def test_supporting_index_routes_are_registered(self):
        paths = {route.path for route in app.routes}
        self.assertIn("/api/surfaces/ndmi/latest", paths)
        self.assertIn("/api/surfaces/ndmi/value", paths)
        self.assertIn("/api/surfaces/ndwi/latest", paths)
        self.assertIn("/api/surfaces/ndwi/value", paths)

    def test_city_without_layers_says_so(self):
        """A city whose layers are not generated yet answers 404 with a reason, never another city's data."""
        from app.core.cities import get_city
        if (get_city("bengaluru").data_dir / "surfaces" / "manifest.json").exists():
            self.skipTest("Bengaluru layers already generated here")
        res = self.client.get("/api/surfaces/ndvi/latest?city=bengaluru")
        self.assertEqual(res.status_code, 404)
        self.assertIn("Bengaluru", res.json()["detail"])
        aqi = self.client.get("/api/surfaces/aqi/latest?city=bengaluru").json()
        self.assertFalse(aqi["available"])
        self.assertEqual(aqi["city"], "bengaluru")

    @needs_db
    def test_system_status(self):
        data = self.client.get("/api/system/status?city=mumbai").json()
        self.assertEqual(data["city"], "mumbai")
        self.assertIn("layers", data)

    @needs_db
    def test_municipalities_latest_uses_the_city_boundaries(self):
        res = self.client.get("/api/municipalities/latest?city=mumbai")
        self.assertEqual(res.status_code, 200)
        self.assertEqual([m["id"] for m in res.json()], ["mumbai", "thane", "mira_bhayandar"])
        res = self.client.get("/api/municipalities/latest?city=delhi")
        self.assertEqual([m["id"] for m in res.json()], ["delhi"])
