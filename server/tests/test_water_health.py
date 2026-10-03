from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
from scipy import ndimage
from fastapi.testclient import TestClient

from gee.ingest_ndvi_ndwi import (
    calculate_mndwi,
    calculate_ndci_proxy,
    calculate_turbidity_proxy,
    calculate_water_health_score,
    water_health_applicable,
)
from app.services.surfaces.water_health_surface import (
    WATER_MASK_EIGHT_CONNECTED,
    WATER_MASK_MIN_COMPONENT_PIXELS,
    _mask_aware_blur_rgba,
    build_water_mask,
    generate_water_health_three_layer,
)
from app.main import app


class FakeEarthEngineImage:
    def __init__(self) -> None:
        self.thresholds = []
        self.component_args = None
        self.mask_applied = False

    def select(self, _band: str):
        return self

    def gte(self, threshold: float):
        self.thresholds.append(threshold)
        return self

    def selfMask(self):
        return self

    def connectedPixelCount(self, *, maxSize: int, eightConnected: bool):
        self.component_args = (maxSize, eightConnected)
        return self

    def updateMask(self, _mask):
        self.mask_applied = True
        return self

    def rename(self, _name: str):
        return self


class WaterHealthTests(unittest.TestCase):
    def test_mndwi_formula(self) -> None:
        self.assertAlmostEqual(calculate_mndwi(0.60, 0.20), 0.5)
        self.assertAlmostEqual(calculate_mndwi(0.10, 0.30), -0.5)

    def test_mndwi_water_mask_uses_threshold(self) -> None:
        self.assertTrue(water_health_applicable(0.25))
        self.assertFalse(water_health_applicable(0.10))
        self.assertTrue(water_health_applicable(0.10, threshold=0.05))

    def test_ndci_proxy_formula(self) -> None:
        self.assertAlmostEqual(calculate_ndci_proxy(0.80, 0.20), 0.6)
        self.assertAlmostEqual(calculate_ndci_proxy(0.10, 0.90), -0.8)

    def test_turbidity_proxy_formula(self) -> None:
        self.assertAlmostEqual(calculate_turbidity_proxy(0.60, 0.20), 0.5)
        self.assertAlmostEqual(calculate_turbidity_proxy(0.20, 0.60), -0.5)

    def test_water_health_score_handles_missing_data(self) -> None:
        self.assertIsNone(calculate_water_health_score(mndwi=None, ndci=None, turbidity_proxy=None, prior_change_pct=None, anomaly_score=None))
        self.assertAlmostEqual(calculate_water_health_score(mndwi=0.55, ndci=0.2, turbidity_proxy=0.35, prior_change_pct=-0.1, anomaly_score=0.3), 0.58125, places=3)

    def test_stronger_condition_risk_lowers_water_health(self) -> None:
        lower_risk = calculate_water_health_score(
            mndwi=0.55,
            ndci=-0.5,
            turbidity_proxy=-0.5,
            prior_change_pct=0.0,
            anomaly_score=0.0,
        )
        higher_risk = calculate_water_health_score(
            mndwi=0.55,
            ndci=0.8,
            turbidity_proxy=0.8,
            prior_change_pct=-0.8,
            anomaly_score=0.8,
        )
        self.assertIsNotNone(lower_risk)
        self.assertIsNotNone(higher_risk)
        self.assertGreater(lower_risk, higher_risk)

    def test_visual_blur_does_not_add_alpha_to_land(self) -> None:
        rgba = np.zeros((3, 3, 4), dtype=np.uint8)
        rgba[1, 1] = [255, 100, 50, 255]
        water_mask = np.zeros((3, 3), dtype=bool)
        water_mask[1, 1] = True

        blurred = _mask_aware_blur_rgba(rgba, water_mask, radius=1.0)

        self.assertTrue(np.all(blurred[~water_mask, 3] == 0))
        self.assertGreater(blurred[1, 1, 3], 0)

    def test_earth_engine_mask_uses_validated_threshold_and_connectivity(self) -> None:
        image = FakeEarthEngineImage()

        build_water_mask(image)

        self.assertEqual(image.thresholds, [0.15, 5])
        self.assertEqual(
            image.component_args,
            (WATER_MASK_MIN_COMPONENT_PIXELS, WATER_MASK_EIGHT_CONNECTED),
        )
        self.assertTrue(image.mask_applied)

    def test_eight_connected_components_and_minimum_size(self) -> None:
        mask = np.array(
            [
                [1, 0, 0, 0, 0, 0, 0],
                [0, 1, 0, 0, 0, 0, 0],
                [0, 0, 0, 0, 0, 0, 0],
                [0, 0, 1, 1, 1, 1, 1],
            ],
            dtype=bool,
        )
        labels, _ = ndimage.label(mask, structure=np.ones((3, 3), dtype=np.uint8))
        sizes = np.bincount(labels.ravel())
        filtered = mask & (sizes[labels] >= WATER_MASK_MIN_COMPONENT_PIXELS)

        self.assertEqual(labels[0, 0], labels[1, 1])
        self.assertFalse(filtered[0, 0])
        self.assertTrue(np.all(filtered[3, 2:7]))

    def test_visualization_png_has_no_alpha_outside_scientific_mask(self) -> None:
        values = np.full((5, 5), -9999.0, dtype=np.float32)
        values[2, 2] = 0.48
        land_mask = np.zeros(values.shape, dtype=bool)
        land_mask[2, 3] = True
        study_mask = np.ones(values.shape, dtype=np.uint8) * 255
        study_mask[4, 4] = 0
        sharp = glow = halo = None
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sharp = root / "sharp.png"
            glow = root / "glow.png"
            halo = root / "halo.png"
            generate_water_health_three_layer(
                values,
                sharp,
                glow,
                halo,
                study_mask,
                {"p05_raw": 0.4, "p25_raw": 0.45, "p50_raw": 0.48, "p75_raw": 0.5, "p95_raw": 0.55, "raw_min": 0.47, "raw_max": 0.48},
                land_visual_mask=land_mask,
            )
            scientific_mask = (values != -9999.0) & (study_mask > 0)
            for path in (sharp, glow, halo):
                alpha = np.asarray(Image.open(path).convert("RGBA"))[:, :, 3]
                if path == sharp:
                    expected_visible = scientific_mask | (land_mask & (study_mask > 0))
                    self.assertEqual(int(alpha[2, 3]), 64)
                    self.assertEqual(tuple(np.asarray(Image.open(path).convert("RGBA"))[2, 3, :3]), (105, 76, 51))
                    water_rgb = tuple(np.asarray(Image.open(path).convert("RGBA"))[2, 2, :3])
                    self.assertGreater(water_rgb[2], water_rgb[0])
                    self.assertGreater(water_rgb[1], water_rgb[0])
                else:
                    expected_visible = scientific_mask
                    self.assertEqual(int(alpha[2, 3]), 0)
                self.assertEqual(int(np.count_nonzero((alpha > 0) & ~expected_visible)), 0)
            sharp_pixels = np.asarray(Image.open(sharp).convert("RGBA"))
            self.assertEqual(int(sharp_pixels[1, 1, 3]), 0)
            self.assertEqual(int(sharp_pixels[4, 4, 3]), 0)

    def test_water_health_surface_urls_are_content_versioned(self) -> None:
        record = {
            "metric": "water_health",
            "sharp_png_filename": "water-health/wh_test.png",
            "glow_png_filename": "water-health/wh_test_glow.png",
            "halo_png_filename": "water-health/wh_test_halo.png",
            "mapbox_coordinates": [[1, 2], [3, 2], [3, 0], [1, 0]],
            "generated_at": "2026-09-30T00:00:00+00:00",
            "methodology": "Sentinel-2",
            "interpretation": "visual test",
            "source_scale_m": 10,
            "nodata_semantics": "transparent",
            "checksums": {
                "sharp_png_sha256": "sharp-hash",
                "glow_png_sha256": "glow-hash",
                "halo_png_sha256": "halo-hash",
            },
        }
        with patch("app.api.routes.load_latest_water_health_surface", return_value=record):
            response = TestClient(app).get("/api/surfaces/water-health/latest")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["sharp_url"], "/surface-assets/water-health/wh_test.png?v=sharp-hash")
        self.assertEqual(data["glow_url"], "/surface-assets/water-health/wh_test_glow.png?v=glow-hash")
        self.assertEqual(data["halo_url"], "/surface-assets/water-health/wh_test_halo.png?v=halo-hash")


if __name__ == "__main__":
    unittest.main()
