"""Tier 1 upgrade: NDMI/NDBI supporting indices, XGBoost feature selection, explanations.
All rasters here are synthetic unit-test fixtures written to temporary folders — never to
the real data/surfaces manifest."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

W, N = 72.80, 19.10          # fixture origin
D10, D20 = 0.0001, 0.0002     # ~10 m and ~20 m pixels in degrees


def _write(path: Path, arr: np.ndarray, res: float):
    meta = dict(driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1, dtype="float32",
                crs="EPSG:4326", transform=from_origin(W, N, res, res), nodata=-9999.0)
    with rasterio.open(path, "w", **meta) as ds:
        ds.write(arr.astype("float32"), 1)


class IndexSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "manifest.json").write_text(json.dumps({"version": 1, "surfaces": {}}))

    def test_publish_records_provenance_and_rejects_out_of_range_values(self):
        from app.services.surfaces import index_surfaces as ix
        arr = np.full((20, 20), 0.30, dtype="float32")
        arr[0, 0] = -9999.0          # nodata stays nodata
        arr[0, 1] = 3.0              # impossible normalised difference -> not kept
        src = self.root / "raw.tif"
        _write(src, arr, D20)
        rec = ix.publish_index_geotiff("ndmi", src, start_date="2026-09-23", end_date="2026-10-07",
                                       image_count=9, output_root=self.root)
        self.assertEqual(rec["scale_m"], 20)
        self.assertFalse(rec["map_layer"])
        self.assertEqual(rec["valid_pixels"], 398)
        self.assertEqual(rec["source_period"], {"start": "2026-09-23", "end": "2026-10-07"})
        ndbi = ix.publish_derived_records(rec, output_root=self.root)
        self.assertEqual(ndbi["value_transform"], "negate")
        self.assertEqual(ndbi["geotiff_filename"], rec["geotiff_filename"])   # one file, not two
        man = json.loads((self.root / "manifest.json").read_text())["surfaces"]
        self.assertIn("ndmi", man)
        self.assertIn("ndbi", man)

    def test_pixel_read_applies_ndbi_transform_and_keeps_nodata(self):
        from app.services.surfaces import index_surfaces as ix
        arr = np.full((20, 20), 0.25, dtype="float32")
        arr[5, 5] = -9999.0
        src = self.root / "raw.tif"
        _write(src, arr, D20)
        rec = ix.publish_index_geotiff("ndmi", src, start_date="2026-09-23", end_date="2026-10-07",
                                       image_count=9, output_root=self.root)
        ix.publish_derived_records(rec, output_root=self.root)
        man = self.root / "manifest.json"
        lon, lat = W + 2.5 * D20, N - 2.5 * D20
        self.assertAlmostEqual(ix.read_index_pixel("ndmi", lon, lat, man)["value"], 0.25)
        self.assertAlmostEqual(ix.read_index_pixel("ndbi", lon, lat, man)["value"], -0.25)
        nd = ix.read_index_pixel("ndmi", W + 5.5 * D20, N - 5.5 * D20, man)
        self.assertTrue(nd["nodata"])
        self.assertIsNone(nd["value"])
        self.assertIsNone(ix.read_index_pixel("ndmi", 80.0, 10.0, man)["value"])   # outside: no value invented


class CellFeatureNdmiTests(unittest.TestCase):
    def test_ndmi_only_on_vegetation_and_ndbi_is_negated_land_mean(self):
        from app.services.ml import cell_features as cf
        root = Path(tempfile.mkdtemp())
        (root / "ndvi").mkdir()
        (root / "indices").mkdir()
        # two 0.004° cells side by side: left green (NDVI 0.7), right built-up (NDVI 0.1)
        ndvi = np.full((40, 80), 0.1, dtype="float32")
        ndvi[:, :40] = 0.7
        _write(root / "ndvi" / "ndvi.tif", ndvi, D10)
        ndmi = np.full((20, 40), -0.2, dtype="float32")
        ndmi[:, :20] = 0.15
        _write(root / "indices" / "ndmi.tif", ndmi, D20)
        man = {"surfaces": {
            "ndvi": {"generation_status": "generated", "geotiff_filename": "ndvi/ndvi.tif"},
            "ndmi": {"generation_status": "generated", "geotiff_filename": "indices/ndmi.tif",
                     "source_period": {"start": "a", "end": "b"}}}}
        (root / "manifest.json").write_text(json.dumps(man))
        cells = [cf.Cell(1, "A", "Mumbai", box(W, N - 0.004, W + 0.004, N), W + 0.002, N - 0.002),
                 cf.Cell(2, "B", "Mumbai", box(W + 0.004, N - 0.004, W + 0.008, N), W + 0.006, N - 0.002)]
        with mock.patch.object(cf, "SURFACE_ROOT", root), mock.patch.object(cf, "MANIFEST", root / "manifest.json"):
            rows, sources = cf.compute_cell_features(cells)
        a, b = rows
        self.assertAlmostEqual(a["ndmi_veg_mean"], 0.15, places=3)
        self.assertIsNone(b["ndmi_veg_mean"])                 # no vegetation -> no moisture value, not zero
        self.assertAlmostEqual(a["ndbi_land_mean"], -0.15, places=3)
        self.assertAlmostEqual(b["ndbi_land_mean"], 0.2, places=3)
        self.assertIn("ndmi", sources)


class XgboostFeatureSelectionTests(unittest.TestCase):
    def setUp(self):
        from app.services.ml import cell_models as cm
        self._p = mock.patch.object(cm, "ML_DIR", Path(tempfile.mkdtemp()))
        self._p.start()

    def tearDown(self):
        self._p.stop()

    def _rows(self, with_ndbi: bool, ndbi_matters: bool):
        rng = np.random.default_rng(7)
        rows = []
        for i in range(40):
            for j in range(40):
                veg = float(rng.uniform(0, 0.8))
                ndbi = float(rng.uniform(-0.3, 0.3))
                lst = 40 - 10 * veg + (12 * ndbi if ndbi_matters else 0) + float(rng.normal(0, 0.4))
                r = {"cell_id": i * 40 + j, "lon": 72.8 + j * 0.003, "lat": 19.0 + i * 0.003,
                     "ndvi_mean": veg, "ndvi_std": 0.1, "veg_frac": veg, "built_frac": 0.8 - veg,
                     "openwater_frac": 0.0, "water_frac": 0.0, "dist_water_m": 2000.0, "lst_mean": lst,
                     "ndbi_land_mean": ndbi if with_ndbi else None,
                     "ndmi_veg_mean": (-ndbi if veg > 0.4 else None) if with_ndbi else None}
                rows.append(r)
        return rows

    def test_ndbi_kept_only_when_it_lowers_spatial_cv_error(self):
        from app.services.ml import cell_models as cm
        out = cm.run_xgboost_lst(self._rows(with_ndbi=True, ndbi_matters=True))
        self.assertIn("NDBI", out["metrics"]["feature_set"])
        self.assertIn("ndbi_land_mean", out["features"])
        self.assertIn("linear_baseline", out["model_comparison"])
        self.assertLess(out["model_comparison"]["xgboost+ NDBI"]["rmse_c"],
                        out["model_comparison"]["xgboost_land_cover"]["rmse_c"])

    def test_not_kept_when_it_adds_nothing_and_skipped_when_missing(self):
        from app.services.ml import cell_models as cm
        out = cm.run_xgboost_lst(self._rows(with_ndbi=True, ndbi_matters=False))
        self.assertEqual(out["features"], cm.XGB_FEATURES)
        out = cm.run_xgboost_lst(self._rows(with_ndbi=False, ndbi_matters=False))
        self.assertEqual(out["features"], cm.XGB_FEATURES)
        self.assertTrue(str(out["model_comparison"]["xgboost+ NDBI"].get("status", "")).startswith("skipped"))
        # drivers never show a feature the cell has no value for
        for res in out["results"].values():
            self.assertTrue(all(d["value"] is not None for d in res["top_drivers"]))


class GreenButHotTests(unittest.TestCase):
    def _ev(self, ndmi_pct=10, lst_pct=88, veg_pct=80):
        from app.services.rag import explainer as E
        ev = {"location": {}, "municipality": "Mumbai", "cell_code": "GSC-1",
              "area": {"ndvi": 0.62, "ndvi_band": "dense vegetation", "lst_c": 41.0, "water_health": None,
                       "aqi": None, "aqi_category": None, "aqi_nearest_station": None, "composite_stress": None,
                       "ndmi": 0.02, "ndbi": -0.02, "basis": {"ndvi": "area", "lst": "area"}},
              "point": {},
              "cell": {"features": {"ndvi_mean": 0.55, "veg_frac": 0.6, "built_frac": 0.2, "openwater_frac": 0.0,
                                    "lst_mean": 40.5, "ndmi_veg_mean": 0.03, "ndbi_land_mean": -0.03},
                       "city_percentiles": {"lst_mean": lst_pct, "veg_frac": veg_pct, "built_frac": 30,
                                            "ndvi_mean": 75, "ndmi_veg_mean": ndmi_pct, "ndbi_land_mean": 40}},
              "models": {}, "data_gaps": []}
        return E, ev

    def test_green_but_hot_gives_several_hypotheses_not_a_cause(self):
        E, ev = self._ev()
        sig = E.derive_signals(ev)
        ids = {s["id"] for s in sig}
        self.assertIn("heat_despite_green", ids)
        self.assertIn("vegetation_dry", ids)
        heat = [f["text"] for f in E.associated_factors(ev, sig, "lst")]
        self.assertTrue(any("several explanations" in t and "dry" in t for t in heat))
        self.assertFalse(any(c in " ".join(heat).lower() for c in ("caused by", "because of", "due to")))
        veg = E.associated_factors(ev, sig, "ndvi")
        self.assertTrue(any(f["kb"] == "ndmi_moisture" for f in veg))
        plan = E.mitigation_plan(ev, sig, "ndvi")
        self.assertTrue(any(i["key"] == "water_green" and i["fits_this_cell"] for i in plan["items"]))

    def test_green_pixel_in_built_up_cell_is_not_green_but_hot(self):
        E, ev = self._ev(veg_pct=10)
        ev["cell"]["features"].update({"veg_frac": 0.01, "built_frac": 0.66, "ndvi_mean": 0.10})
        ev["cell"]["city_percentiles"]["built_frac"] = 95
        ids = {s["id"] for s in E.derive_signals(ev)}     # pixel NDVI is 0.62, but the cell is built-up
        self.assertNotIn("heat_despite_green", ids)

    def test_no_dry_signal_without_moisture_data(self):
        E, ev = self._ev()
        ev["cell"]["features"]["ndmi_veg_mean"] = None
        ev["cell"]["city_percentiles"]["ndmi_veg_mean"] = None
        ev["area"]["ndmi"] = None
        ids = {s["id"] for s in E.derive_signals(ev)}
        self.assertNotIn("vegetation_dry", ids)
        self.assertNotIn("vegetation_moisture_pixel", ids)


class RelationshipTests(unittest.TestCase):
    def test_effect_sizes_by_city_and_class_with_aqi_caution(self):
        from app.services.ml.relationships import compute_relationships, headline
        rng = np.random.default_rng(1)
        rows = []
        for i in range(400):
            veg = float(rng.uniform(0, 0.9))
            rows.append({"municipality": "Mumbai" if i % 2 else "Thane", "openwater_frac": 0.0, "veg_frac": veg,
                         "built_frac": 0.9 - veg, "ndvi_mean": veg * 0.8, "lst_mean": 42 - 9 * veg + rng.normal(0, 1),
                         "aqi_idw": 90 + rng.normal(0, 5), "ndbi_land_mean": None, "wh_mean": None})
        rows.append({"municipality": "Mumbai", "openwater_frac": 0.9, "veg_frac": 0, "built_frac": 0,
                     "ndvi_mean": -0.3, "lst_mean": 28.0})   # water cell: excluded from land pairs
        rel = compute_relationships(rows, n_stations=18)
        h = headline(rel, "ndvi_mean", "lst_mean")
        self.assertLess(h["spearman_rho"], -0.6)
        self.assertEqual(h["strength"], "strong")
        self.assertEqual(h["n"], 400)
        pair = next(p for p in rel["pairs"] if p["x"] == "ndvi_mean" and p["y"] == "lst_mean")
        self.assertIn("Thane", pair["by_municipality"])
        self.assertIn("built-up-dominated", pair["by_land_class"])
        aqi = next(p for p in rel["pairs"] if p["y"] == "aqi_idw")
        self.assertIn("18 stations", aqi["caution"])
        self.assertFalse(any(p["x"] == "ndbi_land_mean" for p in rel["pairs"]))   # no data -> no pair
        self.assertFalse(any("p_value" in json.dumps(p) for p in rel["pairs"]))


class CompositeV2Tests(unittest.TestCase):
    def _grids(self):
        lst = np.array([[30, 40, np.nan, 35]], dtype="float32")
        ndvi = np.array([[0.8, 0.0, 0.4, -0.3]], dtype="float32")
        wh = np.array([[np.nan, np.nan, np.nan, 0.45]], dtype="float32")
        region = np.ones_like(lst, dtype=bool)
        return lst, ndvi, wh, region

    def test_missing_is_never_zero_and_needs_two_of_three(self):
        from app.services import composite_v2 as c
        lst, ndvi, wh, region = self._grids()
        comps = c.compute_components(lst, ndvi, wh, None, region)
        score, cover = c.combine(comps)
        self.assertTrue(np.isnan(score[0, 2]))          # LST missing + no AQI -> 1 of 3 -> no score
        self.assertEqual(int(cover[0, 2]), 1)
        self.assertTrue(np.isfinite(score[0, 0]))
        self.assertGreater(score[0, 1], score[0, 0])     # hot + bare > cool + green
        self.assertTrue(np.isnan(comps["surface"][0, 3]))  # fewer than 30 water pixels -> water not scaled

    def test_water_fills_the_surface_slot_and_air_renormalises(self):
        from app.services import composite_v2 as c
        rng = np.random.default_rng(0)
        lst = rng.uniform(26, 44, (1, 200)).astype("float32")
        ndvi = np.where(np.arange(200) < 100, 0.5, -0.3).astype("float32")[None, :]
        wh = np.where(np.arange(200) >= 100, rng.uniform(0.3, 0.6, 200), np.nan).astype("float32")[None, :]
        aqi = np.full((1, 200), np.nan, dtype="float32")
        aqi[0, :50] = 150
        comps = c.compute_components(lst, ndvi, wh, aqi, np.ones_like(lst, dtype=bool))
        self.assertTrue(np.isfinite(comps["surface"][0, 150]))   # water pixel scored by Water Health
        score, cover = c.combine(comps)
        self.assertEqual(int(cover[0, 10]), 3)
        self.assertEqual(int(cover[0, 120]), 2)
        b = c.contributions({"heat": 0.5, "surface": 0.2, "air": None})
        self.assertEqual(b["coverage"], "2 of 3")
        self.assertEqual(b["missing"], ["air"])
        self.assertAlmostEqual(b["components"]["heat"]["weight"] + b["components"]["surface"]["weight"], 1.0, places=3)
        self.assertAlmostEqual(b["score"], (0.4 * 0.5 + 0.35 * 0.2) / 0.75, places=3)
        self.assertIsNone(c.contributions({"heat": 0.5, "surface": None, "air": None}))

    def test_sensitivity_reports_rank_stability(self):
        from app.services import composite_v2 as c
        rng = np.random.default_rng(2)
        comps = {k: rng.uniform(0, 1, (50, 50)).astype("float32") for k in c.COMPONENTS}
        out = c.sensitivity(comps)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(set(out["alternatives"]), set(c.ALTERNATIVE_WEIGHTS))
        self.assertTrue(0 <= out["top_stable_pct"] <= 100)
        self.assertIn("alternative weightings", out["summary"])

    def test_breakdown_signal_names_missing_component(self):
        from app.services.rag import explainer as E
        ev = GreenButHotTests()._ev()[1]
        ev["area"]["composite_breakdown"] = {"score": 0.62, "coverage": "2 of 3", "missing": ["air"],
                                              "components": {"heat": {"value": 0.8, "weight": 0.533, "points": 0.43, "share_pct": 69.0},
                                                             "surface": {"value": 0.4, "weight": 0.467, "points": 0.19, "share_pct": 31.0}}}
        sig = [s for s in E.derive_signals(ev) if s["id"] == "composite_breakdown"]
        self.assertEqual(len(sig), 1)
        self.assertIn("heat 69%", sig[0]["text"])
        self.assertIn("air not available", sig[0]["text"])


class ValidationTests(unittest.TestCase):
    def _stations(self):
        # 8 stations on a smooth east-west AQI gradient (fixture)
        return [{"station_name": f"s{i}", "lat": 19.05 + 0.01 * (i % 2), "lon": 72.82 + 0.02 * i, "aqi": 60 + 10 * i}
                for i in range(8)]

    def test_loso_hides_each_station_and_reports_error(self):
        from app.services.surfaces.aqi_station_surface import loso_validation
        v = loso_validation(self._stations())
        self.assertEqual(v["status"], "ok")
        self.assertEqual(v["n"], 8)
        self.assertGreater(v["mae"], 0)
        self.assertTrue(all("predicted" in r and "observed" in r for r in v["stations"]))
        self.assertEqual(loso_validation(self._stations()[:3])["status"], "insufficient")

    def test_reliability_label_from_distance_and_density(self):
        from app.services.surfaces.aqi_station_surface import loso_validation, reliability
        st = self._stations()
        v = loso_validation(st)
        near = reliability(19.05, 72.82, st, v)
        self.assertEqual(near["label"], "high")
        self.assertIn("typical_error_aqi", near)
        far = reliability(19.30, 73.10, st, v)
        self.assertEqual(far["label"], "low")
        self.assertIsNone(reliability(19.0, 72.9, [], v))

    def test_worldcover_agreement_plausibility_and_hotspot_share(self):
        from app.services.ml.validation import compute_validation
        rng = np.random.default_rng(4)
        rows, wc, xgb = [], {}, {}
        for i in range(300):
            kind = ("built", "tree", "water")[i % 3]
            veg = {"built": 0.05, "tree": 0.8, "water": 0.0}[kind] + rng.uniform(0, 0.05)
            built = {"built": 0.8, "tree": 0.05, "water": 0.0}[kind]
            ow = {"built": 0.0, "tree": 0.0, "water": 0.9}[kind]
            lst = {"built": 40, "tree": 31, "water": 29}[kind] + rng.normal(0, 1)
            rows.append({"cell_id": i, "veg_frac": veg, "built_frac": built, "openwater_frac": ow, "lst_mean": lst,
                         "ndbi_land_mean": None})
            wc[i] = {"built": 0.85 if kind == "built" else 0.05, "tree": 0.85 if kind == "tree" else 0.05,
                     "water": 0.9 if kind == "water" else 0.0}
            if kind == "built" and i % 2:
                xgb[i] = {"flag": "unexplained_heat"}
        out = compute_validation(rows, xgb, None, {"stations": self._stations()}, wc=wc)
        w = out["worldcover"]
        self.assertEqual(w["status"], "ok")
        self.assertGreater(w["built_bare_share"]["spearman_rho"], 0.7)
        self.assertGreater(w["dominant_class_agreement_pct"], 90)
        self.assertTrue(w["lst_physically_plausible"])
        self.assertEqual(w["heat_flags_in_built_bare_pct"]["unexplained_heat"], 100.0)
        self.assertIsNone(w["ndbi_vs_built_bare"])        # no NDBI yet -> not compared, not invented
        self.assertEqual(out["aqi_idw_loso"]["status"], "ok")

    def test_without_reference_it_says_how_to_run_it(self):
        from app.services.ml.validation import compute_validation
        out = compute_validation([], None, None, {}, wc={})
        self.assertEqual(out["worldcover"]["status"], "not_run")
        self.assertIn("build_validation_reference", out["worldcover"]["how"])
        self.assertEqual(out["aqi_idw_loso"]["status"], "not_run")


if __name__ == "__main__":
    unittest.main()