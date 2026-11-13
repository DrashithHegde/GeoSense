"""Tier 2 seasonal history: seasons, station AQI history, analytics.
Synthetic fixtures only. DB tests run inside a transaction that is rolled back, and write
summary files to a temporary folder — the real database and data/history are never touched."""
from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import numpy as np


class SeasonTests(unittest.TestCase):
    def test_same_season_windows_and_matched_partial(self):
        from app.services.history.seasons import comparable_previous, seasons
        ss = seasons(date(2026, 11, 8))
        keys = [s.key for s in ss]
        self.assertIn("2023-pre", keys)
        self.assertIn("2025-post", keys)
        cur = next(s for s in ss if s.key == "2026-post")
        self.assertTrue(cur.partial)
        self.assertEqual(cur.end, date(2026, 11, 7))
        m = next(s for s in ss if s.key == "2025-post-matched")
        self.assertEqual((m.start, m.end), (date(2025, 10, 1), date(2025, 11, 7)))   # same day range
        by = {s.key: s for s in ss}
        self.assertEqual(comparable_previous("2026-post", by).key, "2025-post-matched")
        self.assertEqual(comparable_previous("2025-post", by).key, "2024-post")
        self.assertIsNone(comparable_previous("2023-pre", by))          # nothing earlier: no comparison
        self.assertFalse(any(s.kind == "monsoon" for s in ss))

    def test_too_early_in_a_season_is_skipped(self):
        from app.services.history.seasons import seasons
        keys = [s.key for s in seasons(date(2026, 10, 10))]
        self.assertNotIn("2026-post", keys)
        self.assertNotIn("2025-post-matched", keys)


class StationHistoryTests(unittest.TestCase):
    def _days(self, start, n, value, cov=90.0):
        return [{"value": value, "coverage": {"percentComplete": cov},
                 "period": {"datetimeFrom": {"local": (start + timedelta(days=i)).isoformat() + "T00:00:00+05:30"}}}
                for i in range(n)]

    def test_daily_cpcb_aqi_from_24h_pollutants_and_coverage_rule(self):
        from app.services.history.station_history import daily_aqi, parse_days, season_aggregate
        d0 = date(2025, 10, 1)
        pm10 = parse_days(self._days(d0, 30, 120.0), "pm10", "µg/m³")
        pm25 = parse_days(self._days(d0, 30, 40.0), "pm25", "µg/m³")
        no2 = parse_days(self._days(d0, 30, 30.0), "no2", "µg/m³")
        low = parse_days(self._days(d0, 5, 50.0, cov=40.0), "so2", "µg/m³")
        self.assertEqual(low, {})                       # < 16 h of data: day not used
        days = daily_aqi({"pm10": pm10, "pm25": pm25, "no2": no2})
        self.assertEqual(len(days), 30)
        self.assertEqual(days[d0]["dominant"], "pm10")
        agg = season_aggregate(days, date(2025, 10, 1), date(2025, 12, 31))
        self.assertEqual(agg["days_with_aqi"], 30)
        self.assertEqual(agg["dominant_pollutant"], "pm10")
        self.assertIsNone(season_aggregate(days, date(2025, 10, 1), date(2025, 10, 10)))   # < 15 days

    def test_two_pollutants_is_not_enough_for_an_aqi(self):
        from app.services.history.station_history import daily_aqi, parse_days
        d0 = date(2025, 3, 1)
        days = daily_aqi({"pm10": parse_days(self._days(d0, 20, 90.0), "pm10", "µg/m³"),
                          "no2": parse_days(self._days(d0, 20, 30.0), "no2", "µg/m³")})
        self.assertEqual(days, {})


class HistoryAnalyticsDbTests(unittest.TestCase):
    """Uses the local PostGIS database inside a rolled-back transaction."""

    @classmethod
    def setUpClass(cls):
        try:
            from sqlalchemy import text

            from app.database import SessionLocal
            db = SessionLocal()
            db.execute(text("SELECT 1 FROM cell_history LIMIT 1"))
            cls.cells = [r[0] for r in db.execute(text("SELECT id FROM spatial_cells ORDER BY id LIMIT 400"))]
            db.close()
            if len(cls.cells) < 400:
                raise RuntimeError("not enough cells")
        except Exception as exc:  # no database here -> skip, never fake
            raise unittest.SkipTest(f"database with history tables not available: {exc}")

    def setUp(self):
        from app.database import SessionLocal
        from app.services.history import analytics
        self.db = SessionLocal()
        self.tmp = Path(tempfile.mkdtemp())
        self._p = [mock.patch.object(analytics, "HISTORY_DIR", self.tmp),
                   mock.patch.object(analytics, "SUMMARY_PATH", self.tmp / "s.json"),
                   mock.patch.object(analytics, "CHANGE_IF_PATH", self.tmp / "c.json")]
        for p in self._p:
            p.start()

    def tearDown(self):
        self.db.rollback()
        self.db.close()
        for p in self._p:
            p.stop()

    def _load(self):
        from app.services.history import store
        from app.services.history.seasons import seasons
        rng = np.random.default_rng(5)
        base_lst = rng.normal(34, 2.5, len(self.cells))
        base_ndvi = rng.uniform(0.1, 0.7, len(self.cells))
        self.hot, self.jump = self.cells[7], self.cells[11]
        base_lst[7] = 48.0                                   # persistently hottest
        for s in seasons(date(2026, 11, 8)):
            store.upsert_season(self.db, {"season": s.key, "label": s.label, "kind": s.kind, "year": s.year,
                                          "period_start": s.start.isoformat(), "period_end": s.end.isoformat(),
                                          "partial": s.partial, "matched_for": s.matched_for,
                                          "s2_images": 20, "landsat_images": 6})
            rows = []
            for i, cid in enumerate(self.cells):
                lst = base_lst[i] + (1.0 if s.kind == "pre" else 0.0) + rng.normal(0, 0.4)
                ndvi = base_ndvi[i] + rng.normal(0, 0.02)
                if cid == self.jump and s.key == "2026-post":
                    lst += 9.0
                    ndvi -= 0.35                              # sudden loss of green + heat
                cloudy = (i % 50 == 3 and s.key == "2024-post")
                rows.append({"cell_id": cid, "ndvi": ndvi, "veg_frac": None, "built_frac": None,
                             "openwater_frac": None, "ndmi_veg": None, "ndbi_land": None, "water_frac": None,
                             "wh": None, "lst": None if cloudy else lst, "s2_valid_frac": 0.9,
                             "lst_valid_frac": 0.1 if cloudy else 0.9})
            path = self.tmp / f"cells_{s.key}.csv"
            import csv
            from app.services.history.gee_builder import COLUMNS
            with path.open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=COLUMNS)
                w.writeheader()
                w.writerows(rows)
            store.load_cell_csv(self.db, s.key, path)

    def test_change_persistence_trend_and_change_forest(self):
        from app.services.history import analytics
        self._load()
        summary = analytics.build_summary(self.db)
        self.assertEqual(summary["latest_pair"], ["2026-post", "2025-post-matched"])
        h = analytics.cell_history(self.db, self.jump, summary=summary,
                                   change_if=__import__("json").loads((self.tmp / "c.json").read_text()))
        ch = h["metrics"]["lst"]["change"]
        self.assertTrue(ch["sudden"])
        self.assertGreater(ch["delta"], 8)
        self.assertIn("matched", ch["from"])
        self.assertTrue(h["change_isolation_forest"]["is_anomaly"])
        self.assertNotIn("2025-post-matched", [s["season"] for s in h["seasons"]])   # matched windows not shown
        hot = analytics.cell_history(self.db, self.hot, summary=summary, change_if={})
        p = hot["metrics"]["lst"]["persistence"]
        self.assertTrue(p["persistent"])
        self.assertEqual(p["seasons_flagged"], p["seasons_observed"])
        self.assertFalse(hot["metrics"]["lst"]["change"]["sudden"])
        self.assertIn("pre", hot["metrics"]["lst"]["trend"])             # 4 full pre-monsoon seasons
        self.assertNotIn("post", hot["metrics"]["lst"]["trend"])         # only 3 full post seasons

    def test_cloudy_season_stays_missing(self):
        from app.services.history import analytics
        self._load()
        summary = analytics.build_summary(self.db)
        cid = self.cells[3]
        h = analytics.cell_history(self.db, cid, summary=summary, change_if={})
        lst = {p["season"]: p["value"] for p in h["metrics"]["lst"]["series"]}
        self.assertIsNone(lst["2024-post"])
        self.assertIn("Post-monsoon 2024", h["metrics"]["lst"]["missing"])


class HistorySignalTests(unittest.TestCase):
    def _ev(self):
        from tests.test_upgrade_tier1 import GreenButHotTests
        ev = GreenButHotTests()._ev()[1]
        ev["history"] = {
            "metrics": {"lst": {"label": "LST", "unit": "°C", "missing": [],
                                "series": [{"season": "2025-post", "label": "Post-monsoon 2025", "value": 38.0}],
                                "change": {"from": "Post-monsoon 2025 (01 Oct-07 Nov, matched)",
                                           "to": "Post-monsoon 2026 (to 07 Nov)", "delta": 6.2, "modified_z": 5.1,
                                           "sudden": True, "region_median_delta": 0.4},
                                "persistence": {"seasons_flagged": 5, "seasons_observed": 6,
                                                "description": "hottest 10%", "persistent": True},
                                "trend": {"pre": {"per_year": 0.6, "seasons": 4, "note": "indicative"}}}},
            "station": {"station_name": "Powai", "distance_m": 2400, "method": "x",
                        "series": [{"label": "Post-monsoon 2026 (to 07 Nov)", "aqi_median": 92.0}],
                        "change": {"from": "Post-monsoon 2025 (01 Oct-07 Nov, matched)",
                                   "to": "Post-monsoon 2026 (to 07 Nov)", "delta": 11.0}},
        }
        return ev

    def test_history_signals_follow_the_tab(self):
        from app.services.rag import explainer as E
        ev = self._ev()
        sig = E.focus_order(E.derive_signals(ev), "lst")
        ids = [x["id"] for x in sig]
        self.assertIn("heat_history_change", ids)
        ch = next(x for x in sig if x["id"] == "heat_history_change")
        self.assertEqual(ch["level"], "warning")              # sudden rise in heat
        self.assertIn("+6.2 °C", ch["text"])
        self.assertIn("heat_history_persistent", ids)
        self.assertIn("heat_history_trend", ids)
        lst_keys = E.FOCUS_SIGNALS["lst"]
        self.assertFalse(any(x["id"].startswith("aqi") for x in sig if any(x["id"].startswith(k) for k in lst_keys)))
        qs = [q["id"] for q in E.suggested_questions(ev, "lst")]
        self.assertIn("history", qs)
        text, kb = E.intent_answer("history", ev, sig, "lst")
        self.assertIn("persistent", text)
        self.assertNotIn("Powai", text)                          # AQI history stays on the AQI tab
        text, _ = E.intent_answer("history", ev, sig, "aqi")
        self.assertIn("Powai", text)
        self.assertEqual(E.match_intent("Has it got hotter over the years?", ev, "lst"), "history")

    def test_no_history_no_question_and_honest_answer(self):
        from app.services.rag import explainer as E
        ev = self._ev()
        ev["history"] = None
        self.assertNotIn("history", [q["id"] for q in E.suggested_questions(ev, "lst")])
        text, _ = E.intent_answer("history", ev, [], "lst")
        self.assertIn("no seasonal history", text)


if __name__ == "__main__":
    unittest.main()
