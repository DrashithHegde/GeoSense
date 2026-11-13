"""Tests for local municipality geometry loading; no database writes."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = REPO_ROOT / "server"
for path in (str(REPO_ROOT), str(SERVER_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from app.services import municipality_boundaries as boundaries


class MunicipalityBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        boundaries.load_municipality_boundaries.cache_clear()
        boundaries.load_study_region_geometry.cache_clear()

    def tearDown(self) -> None:
        boundaries.load_municipality_boundaries.cache_clear()
        boundaries.load_study_region_geometry.cache_clear()

    def test_project_assets_load_as_valid_expected_municipalities(self) -> None:
        loaded = boundaries.load_municipality_boundaries()
        self.assertEqual([item["id"] for item in loaded], ["mumbai", "thane", "mira_bhayandar"])
        for item in loaded:
            self.assertTrue(item["shapely_geom"].is_valid)
            self.assertIn(item["geojson"]["type"], ("Polygon", "MultiPolygon"))

    def test_study_region_is_the_union_of_municipality_assets(self) -> None:
        loaded = boundaries.load_municipality_boundaries()
        union = loaded[0]["shapely_geom"].union(loaded[1]["shapely_geom"]).union(loaded[2]["shapely_geom"])
        # the study region is that union with its holes filled (enclaves such as Sanjay Gandhi
        # National Park belong to the study area even where no municipality boundary covers them)
        from shapely.geometry import MultiPolygon, Polygon
        expected = (Polygon(union.exterior) if union.geom_type == "Polygon"
                    else MultiPolygon([Polygon(g.exterior) for g in union.geoms]))
        study_region = boundaries.load_study_region_geometry()

        self.assertTrue(study_region.is_valid)
        self.assertTrue(study_region.equals(expected))
        self.assertTrue(study_region.buffer(1e-9).contains(union))
        self.assertEqual(boundaries.get_study_region_bounds(), tuple(float(value) for value in expected.bounds))

    def test_missing_asset_has_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(boundaries, "BOUNDARY_DIRECTORY", Path(directory)):
            with self.assertRaisesRegex(boundaries.MunicipalityBoundaryError, "missing"):
                boundaries.load_municipality_boundaries()

    def test_invalid_geojson_has_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            valid = {"type": "Feature", "properties": {"id": "mumbai"}, "geometry": {"type": "Polygon", "coordinates": [[[72, 19], [73, 19], [73, 20], [72, 19]]]}}
            (root / "mumbai.geojson").write_text(json.dumps(valid), encoding="utf-8")
            (root / "thane.geojson").write_text("{invalid", encoding="utf-8")
            with patch.object(boundaries, "BOUNDARY_DIRECTORY", root):
                with self.assertRaisesRegex(boundaries.MunicipalityBoundaryError, "Unable to read"):
                    boundaries.load_municipality_boundaries()