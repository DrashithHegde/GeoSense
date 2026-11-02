"""Tests for fixed-window and provenance conflict guards."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = REPO_ROOT / "server"
for path in (str(REPO_ROOT), str(SERVER_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from app.services.source_metadata import ensure_compatible_metadata
from gee.ingest_lst import source_context as lst_source_context
from gee.ingest_ndvi_ndwi import source_context as s2_source_context


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def mappings(self):
        return self

    def one_or_none(self):
        return self.value


class _FakeDb:
    def __init__(self, metadata):
        if "source_metadata" in metadata:
            self.metadata = metadata
        else:
            self.metadata = {
                "source_metadata": metadata,
                "aqi": None,
                "pm25": None,
                "pm10": None,
                "no2": None,
                "ndvi": None,
                "ndwi": None,
                "lst": None,
            }

    def execute(self, *_args, **_kwargs):
        return _ScalarResult(self.metadata)


class SourceMetadataTests(unittest.TestCase):
    def test_fixed_composite_windows_are_enforced(self) -> None:
        self.assertEqual(s2_source_context("2026-08-02", "2026-08-16")["window_days"], 14)
        self.assertEqual(lst_source_context("2026-07-02", "2026-08-16")["window_days"], 45)
        with self.assertRaises(ValueError):
            s2_source_context("2026-08-01", "2026-08-16")
        with self.assertRaises(ValueError):
            lst_source_context("2026-07-03", "2026-08-16")

    def test_conflicting_existing_context_is_rejected(self) -> None:
        observed_at = datetime(2026, 8, 16, tzinfo=timezone.utc)
        context = {"dataset": "COPERNICUS/S2_SR_HARMONIZED", "window_days": 14}
        ensure_compatible_metadata(
            _FakeDb({"ndvi_ndwi": context}),
            zone_id=1,
            observed_at=observed_at,
            key="ndvi_ndwi",
            context=context,
        )
        with self.assertRaises(ValueError):
            ensure_compatible_metadata(
                _FakeDb({"ndvi_ndwi": {"dataset": "COPERNICUS/S2_SR_HARMONIZED", "window_days": 10}}),
                zone_id=1,
                observed_at=observed_at,
                key="ndvi_ndwi",
                context=context,
            )

    def test_legacy_measurement_without_context_is_not_overwritten(self) -> None:
        with self.assertRaises(ValueError):
            ensure_compatible_metadata(
                _FakeDb({"source_metadata": {}, "ndvi": 0.3, "ndwi": 0.1, "aqi": None, "pm25": None, "pm10": None, "no2": None, "lst": None}),
                zone_id=1,
                observed_at=datetime(2026, 8, 16, tzinfo=timezone.utc),
                key="ndvi_ndwi",
                context={"dataset": "COPERNICUS/S2_SR_HARMONIZED", "window_days": 14},
            )
