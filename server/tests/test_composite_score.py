from __future__ import annotations

import unittest

from app.services.composite_score import calculate_composite


class CompositeScoreTests(unittest.TestCase):
    def test_composite_uses_available_components_and_reports_contributions(self) -> None:
        result = calculate_composite(aqi=250, ndvi=0.2, lst=38, water_health_score=0.4)
        self.assertEqual(result["available_components"], ["aqi", "ndvi", "lst", "water_health"])
        self.assertAlmostEqual(sum(result["contributions"].values()), result["score"])
        self.assertIn("water_health", result["contributions"])

    def test_non_water_water_health_is_missing_not_zero(self) -> None:
        result = calculate_composite(aqi=100, ndvi=0.4, lst=30, water_health_score=None)
        self.assertNotIn("water_health", result["contributions"])
        self.assertIn("water_health", result["missing_components"])
        self.assertIsNotNone(result["score"])

    def test_all_missing_is_unavailable(self) -> None:
        result = calculate_composite(aqi=None, ndvi=None, lst=None, water_health_score=None)
        self.assertIsNone(result["score"])
        self.assertEqual(result["status"], "unavailable")

    def test_directionality_is_environmental_stress(self) -> None:
        better = calculate_composite(aqi=40, ndvi=0.7, lst=25, water_health_score=0.9)
        worse = calculate_composite(aqi=300, ndvi=0.0, lst=42, water_health_score=0.2)
        self.assertLess(better["score"], worse["score"])


if __name__ == "__main__":
    unittest.main()