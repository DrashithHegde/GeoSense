"""Fixes from the code review: AQI 48 h rule at use time, guarded pipeline endpoints."""
import unittest
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from app.api import admin_guard
from app.services.surfaces.aqi_station_surface import aqi_expired, reading_age


def _rec(*hours_ago):
    now = datetime.now(timezone.utc)
    return {"stations": [{"observed_at": (now - timedelta(hours=h)).isoformat()} for h in hours_ago]}


class AqiFreshnessAtUseTests(unittest.TestCase):
    def test_layer_expires_when_even_the_newest_reading_is_over_48h(self):
        self.assertFalse(aqi_expired(_rec(2, 20, 60)))      # newest 2 h -> still shown
        self.assertTrue(aqi_expired(_rec(49, 60, 75)))      # all older than 48 h -> hidden
        self.assertFalse(aqi_expired({"stations": []}))     # nothing to judge -> not expired
        age = reading_age(_rec(3, 8, 19))
        self.assertEqual((round(age["newest_h"]), round(age["median_h"]), round(age["oldest_h"])), (3, 8, 19))


class _Req:
    def __init__(self, host, token=""):
        self.client = type("C", (), {"host": host})()
        self.headers = {"x-admin-token": token} if token else {}


class AdminGuardTests(unittest.TestCase):
    def test_local_only_without_token(self):
        import os
        os.environ.pop("ADMIN_TOKEN", None)
        admin_guard.require_admin(_Req("127.0.0.1"))
        with self.assertRaises(HTTPException):
            admin_guard.require_admin(_Req("192.168.1.20"))

    def test_token_required_when_set(self):
        import os
        os.environ["ADMIN_TOKEN"] = "s3cret"
        try:
            admin_guard.require_admin(_Req("10.0.0.5", "s3cret"))
            with self.assertRaises(HTTPException):
                admin_guard.require_admin(_Req("127.0.0.1", "wrong"))
        finally:
            os.environ.pop("ADMIN_TOKEN", None)

    def test_one_run_at_a_time(self):
        ran = []
        with admin_guard.PIPELINE_LOCK:
            admin_guard.run_exclusive(lambda: ran.append(1))   # lock held -> skipped
        admin_guard.run_exclusive(lambda: ran.append(2))
        self.assertEqual(ran, [2])



class AqiAutoRefreshTests(unittest.TestCase):
    def test_failed_or_thin_refresh_keeps_the_current_layer(self):
        from unittest import mock
        from app.services.surfaces import aqi_refresh
        import openaq.derive_aqi_grid as grid
        from app.services.surfaces import aqi_station_surface as surf
        with mock.patch.object(grid, "collect_station_aqi_points", side_effect=RuntimeError("offline")), \
             mock.patch.object(surf, "build_aqi_surface") as build:
            self.assertEqual(aqi_refresh.refresh("test")["status"], "failed")
            build.assert_not_called()
        with mock.patch.object(grid, "collect_station_aqi_points", return_value=([], 0, 0)), \
             mock.patch.object(surf, "build_aqi_surface") as build:
            self.assertEqual(aqi_refresh.refresh("test")["status"], "kept_previous")
            build.assert_not_called()
        self.assertFalse(aqi_refresh.STATE["running"])

    def test_only_one_refresh_at_a_time(self):
        from app.services.surfaces import aqi_refresh
        with aqi_refresh._LOCK:
            self.assertEqual(aqi_refresh.refresh("test")["status"], "already_running")

    def test_needs_refresh_by_layer_age(self):
        from unittest import mock
        from app.services.surfaces import aqi_refresh
        with mock.patch.object(aqi_refresh, "layer_age_hours", return_value=2.0):
            self.assertFalse(aqi_refresh.needs_refresh())
        with mock.patch.object(aqi_refresh, "layer_age_hours", return_value=7.0):
            self.assertTrue(aqi_refresh.needs_refresh())
        with mock.patch.object(aqi_refresh, "layer_age_hours", return_value=None):
            self.assertTrue(aqi_refresh.needs_refresh())


class AqiAutoRefreshSwitchTests(unittest.TestCase):
    def test_enabled_reads_settings_and_can_be_switched_off(self):
        import os
        from app.services.surfaces import aqi_refresh
        aqi_refresh.enabled()                          # must not raise (it runs at start-up)
        os.environ["AQI_AUTO_REFRESH"] = "0"
        try:
            self.assertFalse(aqi_refresh.enabled())
        finally:
            os.environ.pop("AQI_AUTO_REFRESH", None)


if __name__ == "__main__":
    unittest.main()