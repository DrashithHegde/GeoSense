from __future__ import annotations

import unittest

from gee.ingest_ndvi_ndwi import (
    calculate_mndwi,
    calculate_ndci_proxy,
    calculate_turbidity_proxy,
    calculate_water_health_score,
    water_health_applicable,
)


class WaterHealthTests(unittest.TestCase):
    def test_mndwi_formula(self) -> None:
        self.assertAlmostEqual(calculate_mndwi(0.60, 0.20), 0.5)
        self.assertAlmostEqual(calculate_mndwi(0.10, 0.30), -0.5)

    def test_mndwi_water_mask_uses_threshold(self) -> None:
        self.assertTrue(water_health_applicable(0.25, threshold=0.0))
        self.assertFalse(water_health_applicable(-0.10, threshold=0.0))
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


if __name__ == "__main__":
    unittest.main()
