"""NDVI surface tests use a local raster; no synthetic production data or GEE calls."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = REPO_ROOT / "server"
for path in (str(REPO_ROOT), str(SERVER_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from app.main import app
from app.services.surfaces.ndvi_surface import CRS, NODATA_VALUE, ndvi_to_rgba, publish_ndvi_geotiff


class NdviSurfaceTests(unittest.TestCase):
    def _source_tiff(self, directory: Path, values: np.ndarray) -> Path:
        path = directory / "source.tif"
        with rasterio.open(path, "w", driver="GTiff", height=values.shape[0], width=values.shape[1], count=1,
                           dtype="float32", crs=CRS, transform=from_bounds(72.8, 19.0, 72.9, 19.1, values.shape[1], values.shape[0]),
                           nodata=NODATA_VALUE) as dataset:
            dataset.write(values.astype(np.float32), 1)
        return path

    def test_publish_valid_raster_and_manifest(self):
        values = np.array([[0.1, 0.4], [NODATA_VALUE, -0.1]], dtype=np.float32)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "surfaces"
            report = publish_ndvi_geotiff(self._source_tiff(Path(temp), values), start_date="2026-09-01", end_date="2026-09-15", image_count=3, output_root=root)
            self.assertEqual(report["valid_pixels"], 3)
            self.assertEqual(report["nodata_pixels"], 1)
            self.assertEqual(report["source_scale_m"], 10)
            with rasterio.open(root / report["geotiff_filename"]) as output:
                self.assertEqual(output.crs.to_string(), CRS)
                self.assertEqual(output.nodata, NODATA_VALUE)
            alpha = ndvi_to_rgba(values)[:, :, 3]
            self.assertEqual(int((alpha == 0).sum()), 1)
            self.assertTrue((root / report["png_filename"]).exists())
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["surfaces"]["ndvi"]["metric"], "ndvi")

    def test_empty_or_invalid_raster_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self._source_tiff(Path(temp), np.full((2, 2), NODATA_VALUE, dtype=np.float32))
            with self.assertRaisesRegex(ValueError, "zero valid"):
                publish_ndvi_geotiff(path, start_date="2026-09-01", end_date="2026-09-15", image_count=1, output_root=Path(temp) / "surfaces")

    def test_endpoint_contract_and_absence(self):
        client = TestClient(app)
        with patch("app.api.routes.load_latest_ndvi_surface", return_value=None):
            self.assertEqual(client.get("/api/surfaces/ndvi/latest").status_code, 404)
        record = {"metric": "ndvi", "png_filename": "ndvi/test.png", "mapbox_coordinates": [[1,2],[3,2],[3,0],[1,0]],
                  "generated_at": "2026-09-15T00:00:00+00:00", "source_timestamp": "2026-09-15T00:00:00+00:00",
                  "source_period": {"start": "2026-09-01", "end": "2026-09-15"}, "source": "GEE", "dataset": "S2",
                  "methodology": "median", "interpretation": "vegetation", "preprocessing": {}, "source_scale_m": 10,
                  "nodata_semantics": "transparent"}
        with patch("app.api.routes.load_latest_ndvi_surface", return_value=record):
            response = client.get("/api/surfaces/ndvi/latest")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["image_url"], "/surface-assets/ndvi/test.png")
