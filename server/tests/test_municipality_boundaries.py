"""Tests for local municipality geometry loading, per city; no database writes."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.core.cities import use_city  # noqa: E402
from app.services import municipality_boundaries as boundaries  # noqa: E402


class MunicipalityBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        boundaries.clear_cache()

    def tearDown(self) -> None:
        boundaries.clear_cache()

    def test_project_assets_load_as_valid_expected_municipalities(self) -> None:
        expected = {"mumbai": ["mumbai", "thane", "mira_bhayandar"], "delhi": ["delhi"], "bengaluru": ["bengaluru"]}
        for cid, ids in expected.items():
            with use_city(cid):
                loaded = boundaries.load_municipality_boundaries()
            self.assertEqual([item["id"] for item in loaded], ids)
            for item in loaded:
                self.assertTrue(item["shapely_geom"].is_valid)
                self.assertIn(item["geojson"]["type"], ("Polygon", "MultiPolygon"))

    def test_study_region_is_the_union_of_municipality_assets(self) -> None:
        loaded = boundaries.load_municipality_boundaries("mumbai")
        union = loaded[0]["shapely_geom"].union(loaded[1]["shapely_geom"]).union(loaded[2]["shapely_geom"])
        # the study region is that union with its holes filled (enclaves such as Sanjay Gandhi
        # National Park belong to the study area even where no municipality boundary covers them)
        from shapely.geometry import MultiPolygon, Polygon
        expected = (Polygon(union.exterior) if union.geom_type == "Polygon"
                    else MultiPolygon([Polygon(g.exterior) for g in union.geoms]))
        study_region = boundaries.load_study_region_geometry("mumbai")
        self.assertTrue(study_region.is_valid)
        self.assertTrue(study_region.equals(expected))
        self.assertTrue(study_region.buffer(1e-9).contains(union))
        self.assertEqual(boundaries.get_study_region_bounds("mumbai"), tuple(float(v) for v in expected.bounds))

    def test_cities_do_not_overlap(self) -> None:
        regions = {c: boundaries.load_study_region_geometry(c) for c in ("mumbai", "delhi", "bengaluru")}
        self.assertFalse(regions["mumbai"].intersects(regions["delhi"]))
        self.assertFalse(regions["delhi"].intersects(regions["bengaluru"]))
        # sizes in the expected range (km², rough): Delhi NCT ~1,490, BBMP ~710
        import math
        for c, lo, hi in (("delhi", 1400, 1600), ("bengaluru", 650, 780)):
            g = regions[c]
            lat = (g.bounds[1] + g.bounds[3]) / 2
            km2 = g.area * 111.32 ** 2 * math.cos(math.radians(lat))
            self.assertTrue(lo < km2 < hi, (c, km2))

    def test_missing_asset_has_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(boundaries, "boundary_directory", lambda city_id=None: Path(directory)):
            with self.assertRaisesRegex(boundaries.MunicipalityBoundaryError, "missing"):
                boundaries.load_municipality_boundaries("mumbai")

    def test_invalid_geojson_has_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            valid = {"type": "Feature", "properties": {"id": "mumbai"},
                     "geometry": {"type": "Polygon", "coordinates": [[[72, 19], [73, 19], [73, 20], [72, 19]]]}}
            (root / "mumbai.geojson").write_text(json.dumps(valid), encoding="utf-8")
            (root / "thane.geojson").write_text("{invalid", encoding="utf-8")
            with patch.object(boundaries, "boundary_directory", lambda city_id=None: root):
                with self.assertRaisesRegex(boundaries.MunicipalityBoundaryError, "Unable to read"):
                    boundaries.load_municipality_boundaries("mumbai")
