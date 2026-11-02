"""Tests for the heatmap renderer, station AQI surface, RAG retrieval, explainer and
LLM validation. Station inputs below are unit-test fixtures (never written to the
real manifest — a temporary manifest path is used)."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from rasterio.transform import from_bounds

from app.services.municipality_boundaries import get_study_region_bounds
from app.services.rag import retriever
from app.services.rag.explainer import (
    build_evidence, classification, derive_signals, recommendations, validate_llm,
)
from app.services.surfaces import aqi_station_surface as aqs
from app.services.surfaces.heatmap_render import (
    VIBRANT_STOPS, RenderSpec, normalized_smooth, quantile_knots, render_heatmap, study_region_mask,
)


class HeatmapRendererTests(unittest.TestCase):
    def setUp(self):
        w, s, e, n = get_study_region_bounds()
        self.shape = (220, 160)
        self.transform = from_bounds(w, s, e, n, self.shape[1], self.shape[0])
        rng = np.random.default_rng(0)
        self.values = rng.uniform(0.3, 0.6, self.shape).astype("float32")
        self.valid = np.ones(self.shape, bool)
        self.valid[:, :40] = False  # a NoData stripe

    def _spec(self):
        return RenderSpec("t", VIBRANT_STOPS, quantile_knots(self.values[self.valid], 7), [""] * 7,
                          sharp_sigma=1.5, glow_sigma=5, halo_sigma=12)

    def test_nothing_drawn_outside_study_region_even_after_glow(self):
        out = render_heatmap(self.values, self.valid, self.transform, self._spec())
        region = study_region_mask(self.shape, self.transform)
        for layer in ("sharp", "glow", "halo"):
            self.assertEqual(int(out[layer][~region][..., 3].max()), 0, layer)

    def test_nodata_is_never_filled_far_from_valid_pixels(self):
        out = render_heatmap(self.values, self.valid, self.transform, self._spec())
        self.assertEqual(int(out["sharp"][:, :25][..., 3].max()), 0)

    def test_normalized_smooth_preserves_constant_field(self):
        v = np.full((50, 50), 0.42, "float32")
        w = np.zeros((50, 50), "float32")
        w[10:40, 10:40] = 1
        sm, _ = normalized_smooth(v * w, w, 3.0)
        self.assertTrue(np.allclose(sm[10:40, 10:40], 0.42, atol=1e-4))

    def test_quantile_knots_monotonic(self):
        k = quantile_knots(np.full(1000, 0.5), 7)
        self.assertTrue(all(b > a for a, b in zip(k, k[1:])))


class AqiStationSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.manifest = self.tmp / "manifest.json"
        self.now = datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc)

    def _st(self, i, lat, lon, aqi, age_h=2, cpcb=True):
        return {"station_id": i, "station_name": f"fixture-{i}", "lat": lat, "lon": lon, "aqi": aqi,
                "provider": "CPCB", "is_cpcb_mpcb": cpcb, "dominant_pollutant": "pm10",
                "observed_at": self.now - timedelta(hours=age_h), "freshness": "fresh"}

    def test_insufficient_stations_produces_no_surface(self):
        rec = aqs.build_aqi_surface([self._st(1, 19.0, 72.85, 120), self._st(2, 19.1, 72.9, 90, age_h=80)],
                                    manifest_path=self.manifest, out_dir=self.tmp, now=self.now)
        self.assertEqual(rec["generation_status"], "insufficient_coverage")
        self.assertFalse(rec["available"])
        self.assertEqual(rec["audit"]["stations_eligible"], 1)
        self.assertIn("stale", rec["audit"]["stations_rejected"][0]["reason"])
        self.assertFalse(list(self.tmp.glob("*.tif")))

    def test_surface_is_bounded_by_station_values(self):
        sts = [self._st(1, 19.0, 72.84, 80), self._st(2, 19.08, 72.88, 160),
               self._st(3, 19.2, 72.95, 110), self._st(4, 19.15, 72.85, 140)]
        rec = aqs.build_aqi_surface(sts, manifest_path=self.manifest, out_dir=self.tmp, now=self.now)
        self.assertEqual(rec["generation_status"], "generated")
        self.assertGreaterEqual(rec["aqi_min"], 80 - 1e-3)
        self.assertLessEqual(rec["aqi_max"], 160 + 1e-3)
        data = json.loads(self.manifest.read_text())
        self.assertEqual(data["surfaces"]["aqi"]["stations"][0]["category"]["name"], "Satisfactory")

    def test_non_cpcb_and_future_rejected(self):
        ok, rej = aqs.eligible_stations([self._st(1, 19, 72.8, 50, cpcb=False), self._st(2, 19, 72.8, 50, age_h=-5)],
                                        self.now)
        self.assertEqual(ok, [])
        self.assertEqual({r["reason"] for r in rej}, {"not CPCB/MPCB-backed", "future timestamp"})

    def test_cpcb_category_boundaries(self):
        self.assertEqual(aqs.cpcb_category(50)["name"], "Good")
        self.assertEqual(aqs.cpcb_category(101)["name"], "Moderate")
        self.assertEqual(aqs.cpcb_category(450)["name"], "Severe")


class RagTests(unittest.TestCase):
    def test_kb_entries_are_cited(self):
        for d in retriever.load_kb():
            self.assertTrue(d["source"], d["knowledge_id"])
            self.assertFalse(str(d.get("city") or "").startswith("http"), d["knowledge_id"])

    def test_retrieval_relevance(self):
        top = retriever.retrieve("urban heat island built-up surface temperature", k=3)
        self.assertIn("uhi", [d["knowledge_id"] for d in top])
        top = retriever.retrieve("algae chlorophyll in lake water", k=3)
        self.assertIn("ndci", [d["knowledge_id"] for d in top])

    def test_validator_rejects_invented_numbers_and_causal_claims(self):
        out = {"summary": "LST is 51.7 °C and this is caused by traffic.", "citations": ["made_up"]}
        problems = validate_llm(out, json.dumps({"lst": 46.2}), {"uhi"})
        self.assertTrue(any("51.7" in p for p in problems))
        self.assertTrue(any("caused by" in p for p in problems))
        self.assertTrue(any("made_up" in p for p in problems))

    def test_validator_accepts_grounded_text(self):
        out = {"summary": "Cell LST of 46.2 °C is associated with a 65% built-up share.", "citations": ["uhi"]}
        self.assertEqual(validate_llm(out, json.dumps({"lst": 46.2, "built": 0.65}), {"uhi"}), [])


class ExplainerTests(unittest.TestCase):
    def _analysis(self, aqi_available=False):
        return {
            "location": {"longitude": 72.86, "latitude": 19.09},
            "municipality": {"name": "Mumbai"},
            "pixel": {
                "ndvi": {"value": 0.05, "nodata": False},
                "lst": {"value_c": 44.5, "nodata": False, "qc_flag": None},
                "water_health": {"value": None, "nodata": True},
                "aqi": {"value": 180, "nodata": False, "available": True, "category": {"name": "Moderate"},
                        "nearest_station": {"station_name": "x", "distance_m": 900}}
                if aqi_available else {"available": False, "nodata": True, "reason": "no stations"},
            },
            "cell": {
                "cell_code": "GSC-1", "features": {"built_frac": 0.9, "veg_frac": 0.02, "lst_mean": 46.0},
                "models": {"xgboost_lst_residual_v1": {"evidence": {
                    "observed_lst_c": 46.0, "expected_lst_c": 39.0, "residual_c": 7.0, "flag": "unexplained_heat",
                    "top_drivers": [{"feature": "built_frac", "label": "built/bare share", "effect_c": 3.0, "value": 0.9}],
                    "cv_metrics": {"r2_spatial_cv": 0.49, "rmse_c": 2.9}}}},
            },
        }

    def test_heat_signal_and_recommendation(self):
        ev = build_evidence(self._analysis())
        sig = derive_signals(ev)
        ids = {s["id"] for s in sig}
        self.assertIn("unexplained_heat", ids)
        self.assertIn("heat", {r["theme"] for r in recommendations(sig)})
        self.assertEqual(classification(sig), "anomaly")
        self.assertTrue(any("CPCB AQI unavailable" in g for g in ev["data_gaps"]))

    def test_aqi_signal_only_when_available(self):
        sig = derive_signals(build_evidence(self._analysis(aqi_available=True)))
        self.assertIn("aqi", {s["id"] for s in sig})
        sig = derive_signals(build_evidence(self._analysis(aqi_available=False)))
        self.assertNotIn("aqi", {s["id"] for s in sig})


class IsolationForestScopeTests(unittest.TestCase):
    def test_water_cells_are_not_scored_by_isolation_forest(self):
        from unittest import mock
        from app.services.ml import cell_models as cm
        mock.patch.object(cm, "ML_DIR", Path(tempfile.mkdtemp())).start()
        rng = np.random.default_rng(1)
        rows = []
        for i in range(400):
            water = 0.9 if i < 40 else 0.0
            rows.append({"cell_id": i, "ndvi_land_mean": float(rng.uniform(.2, .7)), "ndvi_std": float(rng.uniform(.05, .2)),
                         "veg_frac": float(rng.uniform(0, .5)) * (1 - water), "built_frac": float(rng.uniform(0, .5)) * (1 - water),
                         "openwater_frac": water, "lst_mean": float(rng.uniform(28, 40)), "lst_std": float(rng.uniform(.5, 2))})
        res = cm.run_isolation_forest(rows)
        self.assertEqual(res["excluded_water_cells"], 40)
        self.assertTrue(all(i >= 40 for i in res["results"]))


class LlmFallbackTests(unittest.TestCase):
    def test_rate_limited_provider_falls_back_to_next(self):
        import asyncio
        from unittest import mock
        import httpx
        from app.services.rag import llm

        class R:
            def __init__(self, code, body=None):
                self.status_code, self.body = code, body or {}
            def raise_for_status(self):
                if self.status_code != 200:
                    raise httpx.HTTPStatusError("x", request=None, response=self)
            def json(self):
                return self.body

        async def post(_self, url, **kw):
            if "googleapis" in url:
                return R(429)
            return R(200, {"choices": [{"message": {"content": '{"answer": "ok"}'}}]})

        keys = {"GEMINI_API_KEY": "g", "GROQ_API_KEY": "q"}
        llm._CACHE.clear(); llm._COOLDOWN.clear()
        with mock.patch.object(llm, "_env", lambda n: keys.get(n)), mock.patch.object(httpx.AsyncClient, "post", post):
            out, meta = asyncio.run(llm.complete_json("sys-test", "user-test"))
        self.assertEqual(out["answer"], "ok")
        self.assertEqual(meta["provider"], "groq")
        self.assertIn("gemini", meta["fallback_from"])


class LayerIsolationForestTests(unittest.TestCase):
    def setUp(self):
        # never overwrite the real trained models in data/ml with test fixtures
        from unittest import mock
        from app.services.ml import cell_models as cm
        self._patch = mock.patch.object(cm, "ML_DIR", Path(tempfile.mkdtemp()))
        self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def _rows(self):
        rng = np.random.default_rng(3)
        rows = []
        for i in range(30):
            for j in range(30):
                rows.append({"cell_id": i * 30 + j, "lon": 72.85 + j * 0.003, "lat": 19.0 + i * 0.003,
                             "openwater_frac": 0.0, "veg_frac": 0.4, "built_frac": 0.3,
                             "ndvi_land_mean": float(rng.normal(0.45, 0.05)), "ndvi_std": float(rng.uniform(.05, .1)),
                             "lst_mean": float(rng.normal(33, 1.0)), "lst_std": float(rng.uniform(.5, 1)),
                             "wh_mean": None, "wh_std": None, "aqi_idw": float(80 + i)})
        rows[455]["lst_mean"] = 48.0  # an isolated hotspot
        return rows

    def test_every_layer_gets_its_own_model_and_hotspot_is_flagged(self):
        from app.services.ml import cell_models as cm
        out = cm.run_layer_isolation_forests(self._rows())
        self.assertEqual(out["lst"]["status"], "ok")
        self.assertEqual(out["ndvi"]["status"], "ok")
        self.assertEqual(out["aqi"]["status"], "ok")
        self.assertEqual(out["water_health"]["status"], "insufficient")  # no water: nothing invented
        hot = out["lst"]["results"][455]
        self.assertTrue(hot["is_anomaly"])
        self.assertEqual(hot["direction"], "high")
        self.assertGreater(hot["z_scores"]["lst_local_diff"], 3)

    def test_station_isolation_forest_uses_real_sub_indices_only(self):
        from app.services.ml import cell_models as cm
        st = [{"station_name": f"s{i}", "lat": 19, "lon": 72.9, "aqi": 80,
               "sub_indices": {"pm25": 60 + i, "pm10": 80 + i, "no2": 40 + (i % 3), "so2": None, "o3": 20, "co": 30}}
              for i in range(12)]
        st[5]["sub_indices"]["no2"] = 190  # unusual mix
        st.append({"station_name": "no-data", "lat": 19, "lon": 72.9, "aqi": 50, "sub_indices": None})
        out = cm.run_station_isolation_forest(st)
        self.assertEqual(out["status"], "ok")
        self.assertNotIn("SO₂", out["pollutants"])  # not reported widely -> not used, not filled
        flagged = [x["station_name"] for x in out["stations"] if x["is_anomaly"]]
        self.assertIn("s5", flagged)
        self.assertEqual(out["eligible"], 12)


class ExplainerQualityTests(unittest.TestCase):
    def _analysis(self):
        return ExplainerTests()._analysis()

    def test_favourable_multivariate_outlier_is_not_a_warning(self):
        a = self._analysis()
        a["cell"]["models"]["isolation_forest_cell_v2"] = {"evidence": {
            "is_anomaly": True, "score_percentile": 99,
            "dominant_deviations": [{"feature": "veg_land_frac", "label": "dense-vegetation share of land", "z": 3.1, "direction": "above"},
                                    {"feature": "lst_mean", "label": "LST (mean)", "z": -2.4, "direction": "below"}]}}
        sig = derive_signals(build_evidence(a))
        fav = [x for x in sig if x["id"] == "multivariate_outlier_favourable"]
        self.assertTrue(fav and fav[0]["level"] == "notice")

    def test_tabs_never_empty_when_data_missing(self):
        sig = derive_signals(build_evidence(self._analysis()))
        ids = {x["id"] for x in sig}
        self.assertIn("water_not_applicable", ids)   # no water in the fixture cell
        self.assertIn("aqi_unavailable", ids)        # AQI unavailable in the fixture

    def test_action_question_gets_a_recommendation(self):
        import asyncio
        from app.core.config import get_settings
        from app.services.rag import explainer as ex
        st = get_settings()
        old = (st.gemini_api_key, st.groq_api_key, st.anthropic_api_key, st.openai_api_key)
        st.gemini_api_key = st.groq_api_key = st.anthropic_api_key = st.openai_api_key = None
        try:
            r = asyncio.run(ex.answer_question("What would cool this block?", self._analysis(), "lst"))
        finally:
            st.gemini_api_key, st.groq_api_key, st.anthropic_api_key, st.openai_api_key = old
        self.assertIn("What could help", r["answer"])
        self.assertIn("roof", r["answer"])


class ValidatorFlagClaimTests(unittest.TestCase):
    def test_flag_claim_rejected_when_nothing_flagged(self):
        ev = {"models": {"isolation_forest": {"is_anomaly": False}, "layer_isolation_forest": {"lst": {"is_anomaly": False}}}}
        bad = validate_llm({"summary": "The model flags this cell's AQI as high."}, "{}", set(), ev)
        ok = validate_llm({"summary": "This cell is not flagged by any model."}, "{}", set(), ev)
        self.assertTrue(any("flag" in p for p in bad))
        self.assertEqual(ok, [])

    def test_aqi_layer_model_does_not_use_local_contrast(self):
        from app.services.ml.cell_models import LAYER_IF
        self.assertEqual(LAYER_IF["aqi"]["features"], ["aqi_idw"])


class AiSummaryGuardTests(unittest.TestCase):
    """The AI may only restate checked facts; anything else is dropped."""

    def _run(self, text):
        import asyncio
        from unittest import mock
        from app.services.rag import explainer as ex
        a = ExplainerTests()._analysis(aqi_available=True)

        async def fake(system, user, timeout=30.0):
            return {"plain_summary": text}, {"provider": "test", "model": "t"}
        with mock.patch.object(ex, "ai_enabled", lambda: True), mock.patch.object(ex, "complete_json", fake):
            return asyncio.run(ex.explain_point(a, use_llm=True, focus="lst"))

    def test_good_summary_is_shown(self):
        r = self._run("This cell is among the hottest in the region at 46.0 °C, consistent with its large built-up share.")
        self.assertEqual(r["generation"]["mode"], "llm_summary")
        self.assertTrue(r["ai_summary"])

    def test_invented_number_is_dropped(self):
        r = self._run("The surface reaches 52.3 °C here.")
        self.assertNotIn("ai_summary", r)

    def test_false_aqi_flag_is_dropped(self):
        r = self._run("The AQI model flags this location as unusually polluted.")
        self.assertNotIn("ai_summary", r)

    def test_factors_and_recommendations_never_come_from_ai(self):
        r = self._run("This cell is among the hottest in the region.")
        self.assertTrue(r["explanation"]["why_it_might_be"])            # rule-based
        self.assertTrue(all("cause" not in t.lower() or "not proof" in t.lower()
                            for t in r["explanation"]["why_it_might_be"]))


class HybridRetrievalTests(unittest.TestCase):
    def test_hybrid_is_at_least_as_good_as_keyword_search(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from scripts.eval_rag import evaluate
        bm = evaluate("bm25")
        if not retriever.embeddings_available():
            self.skipTest("embedding model not installed")
        hy = evaluate("hybrid")
        self.assertGreaterEqual(hy["recall_at_5"], bm["recall_at_5"])
        self.assertGreaterEqual(hy["recall_at_5"], 0.85)

    def test_falls_back_to_bm25_without_embeddings(self):
        from unittest import mock
        with mock.patch.object(retriever, "embeddings_available", lambda: False):
            ids = [d["knowledge_id"] for d in retriever.retrieve("algae chlorophyll in lake water", k=3)]
        self.assertIn("ndci", ids)

    def test_every_note_has_a_specific_source(self):
        vague = ("literature", "documents;", "guidance;")
        for d in retriever.load_kb():
            src = d["source"]
            self.assertFalse(any(v in src and "(" not in src for v in vague), d["knowledge_id"])


if __name__ == "__main__":
    unittest.main()
