"""Unit tests for the static derived AQI surface; no network or database needed."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
import rasterio

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = REPO_ROOT / "server"
for path in (str(REPO_ROOT), str(SERVER_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from fastapi.testclient import TestClient
from app.main import app
from app.services.surfaces.aqi_surface import (
    AqiSurfaceConfig,
    CRS,
    NODATA_VALUE,
    estimate_pixel_aqi,
    generate_aqi_surface,
    generate_aqi_grid,
)
from openaq.derive_aqi_grid import idw_estimate


STAMP = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
STATIONS = [
    {"station_id": 1, "station_name": "A", "lat": 19.10, "lon": 72.85, "aqi": 80.0, "observed_at": STAMP},
    {"station_id": 2, "station_name": "B", "lat": 19.20, "lon": 72.95, "aqi": 180.0, "observed_at": STAMP},
]
CONFIG = AqiSurfaceConfig(bounds=(72.80, 19.00, 73.05, 19.28), width=20, height=24, max_interpolation_distance_m=20_000.0)


class AqiSurfaceTests(unittest.TestCase):
    def test_pixel_idw_delegates_to_canonical_implementation(self):
        expected, _nearest, _used = idw_estimate(19.15, 72.90, STATIONS, k=4, max_interp_distance_m=20_000, min_stations=2, power=2.0)
        actual = estimate_pixel_aqi(lat=19.15, lon=72.90, station_points=STATIONS, config=CONFIG)
        self.assertAlmostEqual(actual, expected, places=6)

    def test_no_station_support_is_nodata(self):
        config = AqiSurfaceConfig(bounds=(70.0, 16.0, 70.1, 16.1), width=4, height=4, max_interpolation_distance_m=1_000.0)
        grid = generate_aqi_grid(STATIONS, config)
        self.assertTrue(np.all(grid == NODATA_VALUE))

    def test_empty_support_is_not_published_as_a_surface(self):
        config = AqiSurfaceConfig(bounds=(70.0, 16.0, 70.1, 16.1), width=4, height=4, max_interpolation_distance_m=1_000.0)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "surfaces"
            with self.assertRaisesRegex(ValueError, "no supported pixels"):
                generate_aqi_surface(STATIONS, source_timestamp=STAMP, config=config, output_root=root)
            self.assertFalse((root / "manifest.json").exists())

    def test_artifacts_manifest_and_transparent_nodata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "surfaces"
            report = generate_aqi_surface(STATIONS, source_timestamp=STAMP, config=CONFIG, output_root=root)
            tif = root / report["geotiff_filename"]
            png = root / report["png_filename"]
            self.assertTrue(tif.exists())
            self.assertTrue(png.exists())
            self.assertGreater(report["valid_pixels"], 0)
            self.assertGreater(report["nodata_pixels"], 0)
            self.assertGreaterEqual(report["aqi_statistics"]["min"], 0)
            self.assertLessEqual(report["aqi_statistics"]["max"], 500)
            with rasterio.open(tif) as dataset:
                self.assertEqual(str(dataset.crs), CRS)
                self.assertEqual(dataset.nodata, NODATA_VALUE)
                self.assertEqual((dataset.width, dataset.height), (CONFIG.width, CONFIG.height))
            alpha = np.asarray(Image.open(png).convert("RGBA"))[:, :, 3]
            self.assertEqual(int((alpha == 0).sum()), report["nodata_pixels"])
            self.assertEqual(int((alpha == 255).sum()), report["valid_pixels"])
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["surfaces"]["aqi"]["metric"], "aqi")
            self.assertEqual(manifest["surfaces"]["aqi"]["idw"]["power"], 2.0)

    def test_latest_surface_endpoint_contract(self):
        record = {
            "metric": "aqi", "png_filename": "aqi/aqi_test.png", "mapbox_coordinates": [[1, 2], [3, 2], [3, 0], [1, 0]],
            "generated_at": "2026-09-13T12:00:00+00:00", "source_timestamp": "2026-09-13T12:00:00+00:00",
            "methodology": "OpenAQ CPCB AQI + IDW", "interpretation": "interpolated",
            "nodata_semantics": "transparent", "station_count": 2,
            "idw": {"power": 2.0},
        }
        with patch("app.api.routes.load_latest_aqi_surface", return_value=record):
            response = TestClient(app).get("/api/surfaces/aqi/latest")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["image_url"], "/surface-assets/aqi/aqi_test.png")
        self.assertTrue(response.json()["nodata"])
