"""Multi-city behaviour: city context, per-city paths and thresholds, seasons, retrieval isolation,
AQI category colours. No network; database not needed."""
from __future__ import annotations

import sys
import threading
import unittest
from datetime import date
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.core import cities  # noqa: E402
from app.core.cities import CITIES, DATA_ROOT, city_path, get_city, use_city  # noqa: E402


class CityContextTests(unittest.TestCase):
    def test_default_and_aliases(self):
        self.assertEqual(get_city().id, "mumbai")
        self.assertEqual(get_city("new_delhi").id, "delhi")
        self.assertEqual(get_city("Bangalore").id, "bengaluru")
        with self.assertRaises(cities.UnknownCity):
            get_city("atlantis")

    def test_city_paths_follow_the_city_in_use(self):
        manifest = city_path("surfaces", "manifest.json")
        self.assertEqual(Path(manifest), DATA_ROOT / "surfaces" / "manifest.json")        # Mumbai layout
        with use_city("delhi"):
            self.assertEqual(Path(manifest), DATA_ROOT / "cities" / "delhi" / "surfaces" / "manifest.json")
            self.assertEqual(manifest.parent.name, "surfaces")
            self.assertEqual(city_path("surfaces") / "ndvi", DATA_ROOT / "cities" / "delhi" / "surfaces" / "ndvi")
        self.assertEqual(Path(manifest), DATA_ROOT / "surfaces" / "manifest.json")

    def test_threads_start_on_the_default_city(self):
        seen = []
        with use_city("bengaluru"):
            t = threading.Thread(target=lambda: seen.append(get_city().id))
            t.start()
            t.join()
        self.assertEqual(seen, ["mumbai"])     # background jobs must set their city explicitly

    def test_script_city_argument(self):
        argv = ["x.py", "--only", "lst", "--city", "delhi"]
        self.assertEqual(cities.pop_city_arg(argv), "delhi")
        self.assertEqual(argv, ["x.py", "--only", "lst"])
        argv = ["x.py", "--city=bengaluru"]
        self.assertEqual(cities.pop_city_arg(argv), "bengaluru")
        self.assertEqual(argv, ["x.py"])


class PerCityRulesTests(unittest.TestCase):
    def test_lst_cloud_threshold_is_per_city(self):
        from app.services.qc import lst_qc_min_c
        self.assertEqual(lst_qc_min_c("mumbai"), 20.0)
        with use_city("delhi"):
            self.assertLess(lst_qc_min_c(), 20.0)      # Delhi winters are cooler than coastal Mumbai

    def test_seasons_follow_each_city(self):
        from app.services.history.seasons import seasons
        mum = {s.kind for s in seasons(date(2026, 11, 14), 2024, "mumbai")}
        blr = {s.kind for s in seasons(date(2026, 11, 14), 2024, "bengaluru")}
        self.assertEqual(mum, {"pre", "post"})
        self.assertEqual(blr, {"winter", "pre"})       # Oct-Dec is Bengaluru's cloudy NE monsoon
        labels = [s.label for s in seasons(date(2025, 1, 1), 2024, "bengaluru")]
        self.assertIn("Winter 2024", labels)

    def test_openaq_bbox_contains_the_study_region(self):
        from app.services.municipality_boundaries import get_study_region_bounds
        for cid, c in CITIES.items():
            w, s, e, n = get_study_region_bounds(cid)
            bw, bs, be, bn = c.openaq_bbox
            self.assertTrue(bw <= w and bs <= s and be >= e and bn >= n, cid)

    def test_map_centre_is_inside_the_city(self):
        for cid, c in CITIES.items():
            self.assertEqual(cities.city_for_point(*c.center), cid)


class RetrievalIsolationTests(unittest.TestCase):
    def test_other_cities_local_notes_are_never_used(self):
        from app.services.rag import retriever
        q = "what are the main sources of air pollution in this city"
        for cid, banned in (("delhi", ("mumbai_", "bengaluru_")), ("mumbai", ("delhi_", "bengaluru_")),
                            ("bengaluru", ("mumbai_", "delhi_"))):
            ids = [d["knowledge_id"] for d in retriever.retrieve(q, k=8, city=cid, mode="bm25")]
            self.assertTrue(ids, cid)
            self.assertFalse([i for i in ids if i.startswith(banned)], (cid, ids))
        delhi = [d["knowledge_id"] for d in retriever.retrieve(q, k=8, city="delhi", mode="bm25")]
        self.assertIn("delhi_air_sources", delhi)

    def test_every_city_role_note_exists(self):
        from app.services.rag import retriever
        for c in CITIES.values():
            for role, kid in c.kb.items():
                self.assertIsNotNone(retriever.get(kid), f"{c.id}: {role} -> {kid}")


class EarthEngineTilingTests(unittest.TestCase):
    """A download request must stay under Earth Engine's 48 MiB limit for every city and layer scale."""

    def test_every_city_and_scale_fits_in_the_request_limit(self):
        import math

        from app.services.municipality_boundaries import get_study_region_bounds
        from app.services.surfaces.ee_tiles import EE_REQUEST_LIMIT_BYTES, METRES_PER_DEGREE, tile_grid
        for cid in CITIES:
            west, south, east, north = get_study_region_bounds(cid)
            for scale in (10, 20, 30):
                tiles = tile_grid(west, south, east, north, scale)
                lat = (south + north) / 2
                worst = max(((e - w) * METRES_PER_DEGREE * math.cos(math.radians(lat)) / scale)
                            * ((n - s) * METRES_PER_DEGREE / scale) * 5.8 for _l, w, s, e, n in tiles)
                self.assertLess(worst, EE_REQUEST_LIMIT_BYTES, (cid, scale))
                # tiles cover the box exactly, with shared edges
                self.assertAlmostEqual(min(t[1] for t in tiles), west)
                self.assertAlmostEqual(max(t[3] for t in tiles), east)
                self.assertAlmostEqual(min(t[2] for t in tiles), south)
                self.assertAlmostEqual(max(t[4] for t in tiles), north)

    def test_delhi_at_10_m_needs_more_than_two_tiles(self):
        from app.services.municipality_boundaries import get_study_region_bounds
        from app.services.surfaces.ee_tiles import tile_grid
        self.assertGreater(len(tile_grid(*get_study_region_bounds("delhi"), 10)), 2)


class AqiColourTests(unittest.TestCase):
    def test_gradient_is_smooth_between_category_midpoints(self):
        import numpy as np

        from app.services.surfaces.heatmap_render import AQI_CPCB_STOPS, aqi_band_colours, t_to_rgb, values_to_t
        spec = aqi_band_colours()
        self.assertEqual(spec["knot_values"], [25, 75, 150, 250, 350, 450])
        rgb = lambda v: t_to_rgb(values_to_t(np.array([v], dtype="float32"), spec["knot_values"]), spec["stops_rgb"])[0]
        self.assertTrue(np.allclose(rgb(25), AQI_CPCB_STOPS[0], atol=1))
        self.assertTrue(np.allclose(rgb(250), AQI_CPCB_STOPS[3], atol=1))
        mid = rgb(200)                       # between Moderate and Poor: neither pure colour
        self.assertFalse(np.allclose(mid, AQI_CPCB_STOPS[2], atol=1) or np.allclose(mid, AQI_CPCB_STOPS[3], atol=1))


if __name__ == "__main__":
    unittest.main()