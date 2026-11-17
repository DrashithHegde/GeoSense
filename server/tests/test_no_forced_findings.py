"""Nothing is said that the data does not support: no 'nothing here' lines outside their own tab,
no shared city-wide changes, no weak or absent links."""
import unittest

from app.services.rag import explainer as E
from tests.test_upgrade_tier1 import GreenButHotTests


class NoForcedFindingsTests(unittest.TestCase):
    def test_change_shared_by_the_whole_city_is_not_mentioned(self):
        h = {"metrics": {"lst": {"label": "LST", "unit": "°C", "missing": [], "series": [],
                                 "change": {"from": "Pre 2025", "to": "Pre 2026", "delta": 7.9, "modified_z": 0.2,
                                            "sudden": False, "region_median_delta": 7.6}}}}
        self.assertEqual([s for s in E._history_signals(h) if s["id"].endswith("_change")], [])
        h["metrics"]["lst"]["change"]["delta"] = 9.4          # 1.8 °C more than the city: worth saying
        sig = [s for s in E._history_signals(h) if s["id"].endswith("_change")]
        self.assertEqual(len(sig), 1)
        self.assertIn("+1.8 °C compared with the change across the city", sig[0]["text"])

    def test_absence_lines_only_on_their_own_tab(self):
        ev = GreenButHotTests()._ev()[1]
        ids = {s["id"] for s in E.derive_signals(ev)}
        self.assertIn("water_not_applicable", ids)             # derived ...
        kept = lambda focus: {s["id"] for s in E.derive_signals(ev)                       # noqa: E731
                              if E.ABSENCE_OWNER.get(s["id"], focus) == focus}
        self.assertNotIn("water_not_applicable", kept("composite"))   # ... but not said on Composite
        self.assertNotIn("water_not_applicable", kept("lst"))
        self.assertIn("water_not_applicable", kept("water_health"))   # the Water Health tab says it


if __name__ == "__main__":
    unittest.main()
