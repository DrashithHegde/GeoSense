"""LST surface AOI and fail-closed publication tests."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.transform import from_origin, rowcol
from shapely.geometry import mapping
from fastapi.testclient import TestClient

from app.main import app
from app.services.municipality_boundaries import (
    get_study_region_bounds,
    load_municipality_boundaries,
    load_study_region_geometry,
)
from app.services.surfaces.lst_surface import (
    MANIFEST_PATH,
    NODATA_VALUE,
    _smooth_lst_visualization,
    lst_to_rgba,
    get_lst_export_bounds,
    publish_lst_geotiff,
)


class LstSurfaceTests(unittest.TestCase):
    def test_visual_smoothing_preserves_scientific_values_and_mask(self) -> None:
        values = np.full((7, 7), NODATA_VALUE, dtype=np.float32)
        values[2:5, 2:5] = np.array([[20, 20, 20], [20, 40, 20], [20, 20, 20]], dtype=np.float32)
        original = values.copy()
        valid_mask = values != NODATA_VALUE

        smoothed = _smooth_lst_visualization(values, valid_mask)
        rgba = lst_to_rgba(smoothed, min_c=20, max_c=40, valid_mask=valid_mask)

        self.assertTrue(np.array_equal(values, original))
        self.assertNotEqual(float(smoothed[2, 2]), float(values[2, 2]))
        self.assertTrue(np.all(smoothed[~valid_mask] == NODATA_VALUE))
        self.assertTrue(np.all(rgba[~valid_mask, 3] == 0))
        self.assertTrue(np.all(rgba[valid_mask, 3] > 0))

    def test_export_bounds_are_shared_municipality_union(self) -> None:
        self.assertEqual(get_lst_export_bounds(), get_study_region_bounds())

    def test_existing_zero_coverage_artifact_is_not_published(self) -> None:
        current_tiff = MANIFEST_PATH.parent / "lst" / "lst_20260816T000000Z.tif"
        self.assertTrue(current_tiff.is_file())
        with rasterio.open(current_tiff) as dataset:
            self.assertEqual(dataset.count, 1)
            self.assertEqual(dataset.crs.to_string(), "EPSG:4326")

        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory) / "surfaces"
            with self.assertRaisesRegex(ValueError, "zero valid pixels inside Mumbai"):
                publish_lst_geotiff(
                    current_tiff,
                    start_date="2026-07-02",
                    end_date="2026-08-16",
                    image_count=1,
                    output_root=output_root,
                )
            self.assertFalse((output_root / "manifest.json").exists())
            self.assertFalse((output_root / "lst").exists())

    def test_publish_masks_outside_union_and_records_each_municipality(self) -> None:
        west, south, east, north = get_study_region_bounds()
        pixel_size = 30 / 111319.49079327358
        width = int(np.ceil((east - west) / pixel_size))
        height = int(np.ceil((north - south) / pixel_size))
        transform = from_origin(west, north, pixel_size, pixel_size)
        values = np.full((height, width), -9999.0, dtype=np.float32)
        for municipality in load_municipality_boundaries():
            point = municipality["shapely_geom"].representative_point()
            row, col = rowcol(transform, point.x, point.y)
            values[row, col] = 25.0

        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "source.tif"
            with rasterio.open(
                source_path,
                "w",
                driver="GTiff",
                height=height,
                width=width,
                count=1,
                dtype="float32",
                crs="EPSG:4326",
                transform=transform,
                nodata=-9999.0,
            ) as source:
                source.write(values, 1)

            output_root = Path(directory) / "surfaces"
            report = publish_lst_geotiff(
                source_path,
                start_date="2026-08-16",
                end_date="2026-09-30",
                image_count=4,
                output_root=output_root,
            )

            self.assertEqual(report["valid_pixels"], 3)
            self.assertEqual(
                set(report["valid_pixels_by_municipality"]),
                {"Mumbai", "Thane", "Mira-Bhayandar"},
            )
            self.assertTrue(all(count > 0 for count in report["valid_pixels_by_municipality"].values()))
            output_path = output_root / "lst" / report["files"]["geotiff"]
            with rasterio.open(output_path) as output:
                published = output.read(1)
                union_mask = geometry_mask(
                    [mapping(load_study_region_geometry())],
                    published.shape,
                    output.transform,
                    invert=True,
                    all_touched=True,
                )
                self.assertTrue(np.all(published[~union_mask] == output.nodata))

    def test_lst_surface_endpoint_versions_visual_assets_and_returns_legend(self) -> None:
        record = {
            "metric": "lst",
            "files": {"png": "lst_test.png", "glow_png": "lst_test_glow.png"},
            "checksums": {"png_sha256": "sharp-hash", "glow_png_sha256": "glow-hash"},
            "coordinates": [[72.7, 19.3], [73.1, 19.3], [73.1, 18.8], [72.7, 18.8]],
            "generated_at": "2026-09-30T00:00:00+00:00",
            "timestamp": "20260930T000000Z",
            "source_period": {"start": "2026-08-16", "end": "2026-09-30", "days": 45},
            "dataset": "Landsat 8/9 Collection 2 Tier 1 Level-2",
            "methodology": "Landsat LST",
            "unit": "celsius",
            "scale_m": 30,
            "lst_min_c": -1.23,
            "lst_max_c": 51.03,
            "lst_mean_c": 35.08,
            "lst_median_c": 35.23,
            "glow_threshold_c": 43.0,
            "valid_pixels": 100,
            "visualization": {"color_stops": [{"position": 0, "temperature_c": -1.23, "color": "#2563eb"}]},
        }
        with patch("app.api.routes.load_latest_lst_surface", return_value=record):
            response = TestClient(app).get("/api/surfaces/lst/latest")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["image_url"], "/surface-assets/lst/lst_test.png?v=sharp-hash")
        self.assertEqual(response.json()["glow_url"], "/surface-assets/lst/lst_test_glow.png?v=glow-hash")
        self.assertEqual(response.json()["visualization"], record["visualization"])


if __name__ == "__main__":
    unittest.main()