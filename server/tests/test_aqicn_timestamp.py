"""Regression tests for AQICN source-time conversion."""
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

from aqicn.ingest_aqicn import parse_aqicn_time


class AqicnTimestampTests(unittest.TestCase):
    def test_embedded_offset_converts_to_utc(self) -> None:
        result = parse_aqicn_time({"iso": "2026-08-16T19:00:00+05:30"})
        self.assertEqual(result, datetime(2026, 8, 16, 13, 30, tzinfo=timezone.utc))

    def test_separate_offset_converts_to_utc(self) -> None:
        result = parse_aqicn_time({"s": "2026-08-16 19:00:00", "tz": "+05:30"})
        self.assertEqual(result, datetime(2026, 8, 16, 13, 30, tzinfo=timezone.utc))

    def test_negative_offset_converts_to_utc(self) -> None:
        result = parse_aqicn_time({"s": "2026-08-16 08:00:00", "tz": "-04:00"})
        self.assertEqual(result, datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc))
