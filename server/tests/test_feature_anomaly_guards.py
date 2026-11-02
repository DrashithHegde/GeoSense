"""Safety checks for Isolation Forest input eligibility; no database writes."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = REPO_ROOT / "server"
for path in (str(REPO_ROOT), str(SERVER_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from app.services.feature_anomaly_pipeline import _missing_core_metrics, _select_varying_model_features, _validated_model_matrix


def _row(zone_id: int, *, aqi=85.0, lst=32.0, ndvi=0.3, ndwi=-0.1) -> dict:
    return {"zone_id": zone_id, "values": {"aqi": aqi, "lst": lst, "ndvi": ndvi, "ndwi": ndwi}}


class FeatureAnomalyGuardTests(unittest.TestCase):
    def test_missing_core_metric_is_explicit(self) -> None:
        self.assertEqual(_missing_core_metrics(_row(1, aqi=None)), ["aqi"])
        self.assertEqual(_missing_core_metrics(_row(1, lst=None, ndvi=None)), ["lst", "ndvi"])

    def test_no_eligible_rows_fails_without_matrix(self) -> None:
        with self.assertRaisesRegex(ValueError, "No complete"):
            _validated_model_matrix([])

    def test_too_few_eligible_rows_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 20"):
            _validated_model_matrix([_row(index) for index in range(19)])

    def test_nan_and_infinity_are_rejected(self) -> None:
        rows = [_row(index) for index in range(20)]
        rows[3] = _row(3, ndvi=np.nan)
        with self.assertRaisesRegex(ValueError, "Non-finite"):
            _validated_model_matrix(rows)
        rows[3] = _row(3, ndvi=np.inf)
        with self.assertRaisesRegex(ValueError, "Non-finite"):
            _validated_model_matrix(rows)

    def test_constant_predictor_is_excluded_without_imputation(self) -> None:
        matrix = np.asarray([[85.0, 30.0 + index, 0.1 + index, -0.1 - index] for index in range(20)])
        features, selected, excluded = _select_varying_model_features(matrix)
        self.assertEqual(features, ("lst", "ndvi", "ndwi"))
        self.assertEqual(excluded, ("aqi",))
        self.assertEqual(selected.shape, (20, 3))

    def test_all_constant_predictors_fail_clearly(self) -> None:
        matrix = np.ones((20, 4))
        with self.assertRaisesRegex(ValueError, "constant"):
            _select_varying_model_features(matrix)
