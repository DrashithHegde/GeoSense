"""Time order in the seasonal history: heat first, greenery after; greening with cooling."""
import unittest
from unittest import mock

import numpy as np

from app.services.history import time_order as T


def _season_rows(rng, n, heat_hurts):
    """Two same-season years for n land areas. If heat_hurts, the hottest areas (given their
    greenery) lose greenery by year 2; greening areas cool."""
    ndvi0 = rng.uniform(0.05, 0.85, n)
    lst0 = 42 - 12 * ndvi0 + rng.normal(0, 1.5, n)                 # greener = cooler (snapshot)
    heat_extra = lst0 - (42 - 12 * ndvi0)                           # hotter than its greenery explains
    d_ndvi = rng.normal(0, 0.03, n) - (0.02 * heat_extra if heat_hurts else 0) + 0.04   # +0.04: a wetter year for all
    ndvi1 = ndvi0 + d_ndvi
    lst1 = lst0 - 6 * d_ndvi + rng.normal(0, 0.5, n) + 1.0         # greening -> cooling; +1 °C for all
    a = {i: {"cell_id": i, "ndvi": ndvi0[i], "lst": lst0[i], "ndmi_veg": 0.1, "openwater_frac": 0.0} for i in range(n)}
    b = {i: {"cell_id": i, "ndvi": ndvi1[i], "lst": lst1[i], "ndmi_veg": 0.1 - (0.05 if heat_extra[i] > 2 else 0),
             "openwater_frac": 0.0} for i in range(n)}
    return a, b, lst0


class TimeOrderTests(unittest.TestCase):
    def _data(self, heat_hurts):
        rng = np.random.default_rng(3)
        a, b, lst0 = _season_rows(rng, 3000, heat_hurts)
        p = T._pair(a, b)
        p.update(start="Pre-monsoon 2025", end="Pre-monsoon 2026", start_key="2025-pre", end_key="2026-pre")
        return {"pairs": [p]}, lst0

    def test_detects_heat_before_greenery_loss_and_greening_with_cooling(self):
        data, _ = self._data(heat_hurts=True)
        c = T.city_patterns(data)
        self.assertLess(c["heat_then_greenery"]["rho"], -0.1)
        self.assertIn("lose more greenery", c["heat_then_greenery"]["headline"])
        self.assertLess(c["greening_cooling"]["rho"], -0.3)
        self.assertIn("cooled", c["greening_cooling"]["headline"])

    def test_no_heat_effect_is_not_invented(self):
        # greenery change unrelated to heat: within similar-greenery groups there is no link,
        # even though hot areas start less green (no regression-to-the-mean artefact)
        data, _ = self._data(heat_hurts=False)
        c = T.city_patterns(data)
        self.assertEqual(c["heat_then_greenery"]["strength"], "negligible")

    def test_area_signal(self):
        data, lst0 = self._data(heat_hurts=True)
        p = data["pairs"][0]
        with mock.patch.object(T, "_load", return_value=data):
            # an area that was hot and lost greenery
            i = int(np.argmax(p["heat_pct"] - 1000 * (p["d_ndvi"] > -0.05)))
            out = T.area_time_order(int(p["ids"][i]))
        ids = [s["id"] for s in out["here"]["signals"]]
        self.assertTrue(out["here"]["hot_at_start"])
        self.assertIn("heat_stress_vegetation", ids)


if __name__ == "__main__":
    unittest.main()
