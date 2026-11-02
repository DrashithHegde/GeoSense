"""Tests for OpenAQ AQI ingestion and CPCB calculation."""
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from unittest.mock import patch

import requests

from openaq.client import (
    CO_PPB_TO_UGM3,
    MAX_HTTP_RETRIES,
    OPENAQ_BASE,
    _weighted_window_average,
    aggregate_sensor_measurements,
    collect_station_pollutants,
    fetch_sensor_measurements,
    get_mumbai_station_measurements,
    normalize_concentration,
    within_freshness_window,
)
from openaq.cpcb_aqi import compute_station_cpcb_aqi, compute_pollutant_sub_indices
from openaq.derive_aqi_grid import freshness_label, idw_estimate


def test_cpcb_sub_indices():
    # Test typical values (all in ug/m3)
    pollutants = {
        "pm25": 40.0,   # 31-60 interval -> 51-100 index (should be approx 66)
        "pm10": 150.0,  # 101-250 interval -> 101-200 index
        "no2":  40.0,   # 0-40 interval -> 0-50 index -> 50.0
        "co":   1500.0, # 1.5 mg/m3 -> 1.1-2.0 interval -> 51-100 index (approx 70)
    }
    indices = compute_pollutant_sub_indices(pollutants)
    assert indices["pm25"] is not None
    assert 51 <= indices["pm25"] <= 100
    assert indices["pm10"] is not None
    assert 101 <= indices["pm10"] <= 200
    assert indices["no2"] == 50.0
    assert indices["co"] is not None
    assert 51 <= indices["co"] <= 100
    
    # Missing pollutant
    assert indices.get("so2") is None


def test_station_aqi_calculation():
    # If PM2.5 dominates
    pollutants = {"pm25": 100.0, "pm10": 50.0, "no2": 20.0}
    aqi, dominant, _ = compute_station_cpcb_aqi(pollutants)
    assert aqi is not None
    assert aqi > 200
    assert dominant == "pm25"

    # No valid pollutants
    aqi, dominant, _ = compute_station_cpcb_aqi({"unknown": 100.0})
    assert aqi is None
    assert dominant is None


def test_cpcb_aqi_requires_three_pollutants_including_particulate():
    assert compute_station_cpcb_aqi({"pm25": 20.0, "no2": 30.0})[:2] == (None, None)
    assert compute_station_cpcb_aqi({"no2": 20.0, "so2": 30.0, "o3": 40.0})[:2] == (None, None)
    aqi, dominant, _ = compute_station_cpcb_aqi(
        {"pm25": 20.0, "pm10": 40.0, "no2": 30.0}
    )
    assert aqi == 40
    assert dominant == "pm10"


def test_cpcb_fractional_concentrations_map_to_adjacent_breakpoints():
    low = compute_pollutant_sub_indices({"pm25": 30.4})["pm25"]
    next_band = compute_pollutant_sub_indices({"pm25": 30.5})["pm25"]
    assert low == 50.0
    assert next_band == 51.0


def test_cpcb_invalid_concentrations_are_unavailable():
    indices = compute_pollutant_sub_indices({"pm25": -1.0, "pm10": float("nan")})
    assert indices["pm25"] is None
    assert indices["pm10"] is None


def test_freshness_label():
    now = datetime.now(timezone.utc)
    fresh_time = now - timedelta(hours=2)
    stale_time = now - timedelta(hours=24)
    unavailable_time = now - timedelta(hours=72)
    
    assert freshness_label(fresh_time) == "fresh"
    assert freshness_label(stale_time) == "stale"
    assert freshness_label(unavailable_time) == "unavailable"

def test_unit_conversion():
    ppb_val = 1000.0
    ugm3_val = ppb_val * CO_PPB_TO_UGM3
    assert ugm3_val == 1145.0


def _hourly_measurements(
    start: datetime, values: list[float], interval_minutes: int = 60
) -> list[dict]:
    rows = []
    for index, value in enumerate(values):
        interval_start = start + timedelta(minutes=index * interval_minutes)
        interval_end = interval_start + timedelta(minutes=interval_minutes)
        start_utc = interval_start.isoformat().replace("+00:00", "Z")
        end_utc = interval_end.isoformat().replace("+00:00", "Z")
        rows.append({
            "value": value,
            "period": {"datetimeFrom": {"utc": start_utc}, "datetimeTo": {"utc": end_utc}},
            "coverage": {"datetimeFrom": {"utc": start_utc}, "datetimeTo": {"utc": end_utc}},
            "flagInfo": {"hasFlags": False},
        })
    return rows


def test_unit_normalization_preserves_cpcb_mass_units():
    assert normalize_concentration(1.25, "mg/m³", "pm25") == 1250.0
    assert normalize_concentration(1500, "ng/m3", "pm10") == 1.5
    assert normalize_concentration(1000, "ppb", "co") == CO_PPB_TO_UGM3 * 1000
    assert normalize_concentration(100, "ppb", "no2") is not None
    assert normalize_concentration(5, "ppm", "pm25") is None
    assert normalize_concentration(-1, "ug/m3", "pm25") is None


def test_24_hour_average_requires_at_least_16_covered_hours():
    end = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
    start = end - timedelta(hours=24)
    valid = aggregate_sensor_measurements(
        _hourly_measurements(start, [20.0] * 16),
        pollutant="pm25",
        units="ug/m3",
        window_start=start,
        window_end=end,
    )
    insufficient = aggregate_sensor_measurements(
        _hourly_measurements(start, [20.0] * 15),
        pollutant="pm25",
        units="ug/m3",
        window_start=start,
        window_end=end,
    )
    assert valid is not None
    assert valid["normalized_value"] == 20.0
    assert valid["averaging_period_hours"] == 24
    assert valid["coverage_hours"] == 16.0
    assert insufficient is None


def test_delayed_completed_24_hour_period_passes_existing_coverage_threshold():
    now = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
    latest_end = now - timedelta(hours=25)
    start = latest_end - timedelta(hours=16)
    rows = _hourly_measurements(start, [20.0] * 16)

    result = aggregate_sensor_measurements(
        rows,
        pollutant="pm10",
        units="ug/m3",
        window_start=now - timedelta(hours=72),
        window_end=now,
    )

    assert result is not None
    assert result["averaging_period_hours"] == 24
    assert result["coverage_hours"] == 16.0
    assert result["window_end"] == latest_end
    assert result["observed_at"] == latest_end


def test_delayed_period_with_12_25_hours_still_fails_16_hour_threshold():
    now = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
    latest_end = now - timedelta(hours=25)
    start = latest_end - timedelta(hours=12, minutes=15)
    rows = _hourly_measurements(start, [20.0] * 49, interval_minutes=15)

    coverage = _weighted_window_average(
        [
            (
                start + timedelta(minutes=index * 15),
                start + timedelta(minutes=(index + 1) * 15),
                20.0,
                20.0,
            )
            for index in range(49)
        ],
        latest_end - timedelta(hours=24),
        latest_end,
        0.0,
    )
    assert coverage is not None
    assert coverage["coverage_hours"] == 12.25
    assert aggregate_sensor_measurements(
        rows,
        pollutant="pm10",
        units="ug/m3",
        window_start=now - timedelta(hours=72),
        window_end=now,
    ) is None


def test_wall_clock_window_does_not_reject_valid_completed_period():
    now = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
    latest_end = now - timedelta(hours=25)
    rows = _hourly_measurements(latest_end - timedelta(hours=16), [12.0] * 16)

    result = aggregate_sensor_measurements(
        rows,
        pollutant="no2",
        units="ug/m3",
        window_start=now - timedelta(hours=24),
        window_end=now,
    )

    assert result is not None
    assert result["coverage_hours"] == 16.0
    assert result["window_end"] == latest_end


def test_measurements_older_than_48_hours_are_excluded_from_coverage():
    now = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
    latest_end = now - timedelta(hours=49)
    rows = _hourly_measurements(latest_end - timedelta(hours=16), [18.0] * 16)

    assert aggregate_sensor_measurements(
        rows,
        pollutant="pm25",
        units="ug/m3",
        window_start=now - timedelta(hours=72),
        window_end=now,
    ) is None


def test_delayed_o3_and_co_keep_rolling_8_hour_coverage_rule():
    now = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
    latest_end = now - timedelta(hours=25)
    rows = _hourly_measurements(latest_end - timedelta(hours=6), [30.0] * 6)

    for pollutant in ("o3", "co"):
        result = aggregate_sensor_measurements(
            rows,
            pollutant=pollutant,
            units="ug/m3",
            window_start=now - timedelta(hours=72),
            window_end=now,
        )
        assert result is not None
        assert result["averaging_period_hours"] == 8
        assert result["coverage_hours"] == 6.0
        assert result["window_end"] == latest_end


def test_gaps_are_not_filled_to_manufacture_8_hour_coverage():
    now = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
    latest_end = now - timedelta(hours=25)
    rows = _hourly_measurements(latest_end - timedelta(hours=8), [10.0] * 8)[::2]

    assert aggregate_sensor_measurements(
        rows,
        pollutant="o3",
        units="ug/m3",
        window_start=now - timedelta(hours=72),
        window_end=now,
    ) is None


def test_station_pollutants_apply_freshness_independently_and_report_oldest_used_time():
    now = datetime.now(timezone.utc)
    pollutant_rows = {
        1: _hourly_measurements(now - timedelta(hours=41), [20.0] * 16),
        2: _hourly_measurements(now - timedelta(hours=24), [12.0] * 16),
        3: _hourly_measurements(now - timedelta(hours=65), [8.0] * 16),
    }
    station = {
        "id": 99,
        "name": "Test CPCB station",
        "latitude": 19.0,
        "longitude": 72.9,
        "provider": "CPCB",
        "is_cpcb_mpcb": True,
        "sensors": [
            {"id": 1, "parameter": {"id": 11, "name": "pm25", "units": "ug/m3"}},
            {"id": 2, "parameter": {"id": 12, "name": "no2", "units": "ug/m3"}},
            {"id": 3, "parameter": {"id": 13, "name": "so2", "units": "ug/m3"}},
        ],
    }

    with patch(
        "openaq.client.fetch_sensor_measurements",
        side_effect=lambda _api_key, sensor_id, *_args: pollutant_rows[sensor_id],
    ) as fetch_measurements:
        result = collect_station_pollutants("test-key", station)

    assert result is not None
    assert fetch_measurements.call_count == 3
    for call in fetch_measurements.call_args_list:
        query_start, query_end = call.args[2:4]
        assert query_end - query_start == timedelta(hours=72)
    assert set(result["pollutants"]) == {"pm25", "no2"}
    assert "so2" not in result["pollutants"]
    assert result["pollutant_metadata"]["pm25"]["parameter_id"] == 11
    contributing_times = [
        datetime.fromisoformat(metadata["observed_at"].replace("Z", "+00:00"))
        for metadata in result["pollutant_metadata"].values()
    ]
    assert result["observed_at"] == min(contributing_times)


def test_8_hour_pollutant_uses_supported_rolling_maximum():
    end = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
    start = end - timedelta(hours=24)
    result = aggregate_sensor_measurements(
        _hourly_measurements(start, [10.0] * 16 + [80.0] * 8),
        pollutant="o3",
        units="ug/m3",
        window_start=start,
        window_end=end,
    )
    assert result is not None
    assert result["normalized_value"] == 80.0
    assert result["averaging_period_hours"] == 8
    short_window_start = end - timedelta(hours=8)
    assert aggregate_sensor_measurements(
        _hourly_measurements(short_window_start, [50.0] * 5),
        pollutant="co",
        units="ug/m3",
        window_start=short_window_start,
        window_end=end,
    ) is None


def test_freshness_window_rejects_future_and_over_48_hour_data():
    now = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
    assert within_freshness_window(now - timedelta(hours=48), now=now)
    assert not within_freshness_window(now - timedelta(hours=48, seconds=1), now=now)
    assert not within_freshness_window(now + timedelta(seconds=1), now=now)


def test_idw_prefers_fresh_stations_when_minimum_support_is_met():
    points = [
        {"lat": 19.10, "lon": 72.90, "aqi": 80.0, "freshness": "fresh"},
        {"lat": 19.20, "lon": 72.90, "aqi": 120.0, "freshness": "fresh"},
        {"lat": 19.10, "lon": 72.91, "aqi": 400.0, "freshness": "stale"},
        {"lat": 19.20, "lon": 72.91, "aqi": 450.0, "freshness": "stale"},
    ]
    estimate, _, used = idw_estimate(
        19.15, 72.905, points, k=4, max_interp_distance_m=20_000,
        min_stations=2, power=2.0,
    )
    assert used == 2
    assert 80.0 <= estimate <= 120.0

    one_fresh = points[:1] + points[2:]
    fallback_estimate, _, fallback_used = idw_estimate(
        19.15, 72.905, one_fresh, k=4, max_interp_distance_m=20_000,
        min_stations=2, power=2.0,
    )
    assert fallback_used == 3
    assert fallback_estimate > 120.0


def test_production_station_filter_excludes_non_cpcb_providers():
    cpcb = {"id": 1, "provider": "CPCB", "is_cpcb_mpcb": True}
    airnow = {"id": 2, "provider": "AirNow", "is_cpcb_mpcb": False}
    measurements = {
        1: {"station_id": 1, "pollutants": {"pm25": 10}},
        2: {"station_id": 2, "pollutants": {"pm25": 10}},
    }
    with patch("openaq.client.discover_mmr_stations", return_value=[cpcb, airnow]), patch(
        "openaq.client.collect_station_pollutants",
        side_effect=lambda _key, station, **_kwargs: measurements[station["id"]],
    ) as collect:
        result = get_mumbai_station_measurements("test-key")
    assert [station["station_id"] for station in result] == [1]
    assert collect.call_count == 1


def _http_response(status_code: int, rows: list[dict] | None = None, headers: dict | None = None):
    response = requests.Response()
    response.status_code = status_code
    response.headers.update(headers or {})
    response._content = json.dumps({"results": rows or []}).encode()
    response.raw = BytesIO()
    response.url = f"{OPENAQ_BASE}/sensors/123/measurements"
    return response


def test_sensor_history_retries_http_429():
    start = datetime(2026, 9, 30, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=24)
    throttled = _http_response(429)
    successful = _http_response(200, [{"value": 12.0}])
    with patch("openaq.client._SESSION.request", side_effect=[throttled, successful]) as request, patch(
        "openaq.client._pace_sensor_history_request"
    ), patch("openaq.client.time.sleep") as sleep:
        result = fetch_sensor_measurements("test-key", 123, start, end)

    assert result == [{"value": 12.0}]
    assert request.call_count == 2
    assert sleep.call_count == 1


def test_sensor_history_honors_retry_after_header():
    start = datetime(2026, 9, 30, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=24)
    with patch(
        "openaq.client._SESSION.request",
        side_effect=[_http_response(429, headers={"Retry-After": "12"}), _http_response(200)],
    ), patch("openaq.client._pace_sensor_history_request"), patch("openaq.client.time.sleep") as sleep:
        fetch_sensor_measurements("test-key", 123, start, end)

    sleep.assert_called_once_with(12.0)


def test_sensor_history_retry_exhaustion_is_bounded():
    start = datetime(2026, 9, 30, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=24)
    with patch("openaq.client._SESSION.request", side_effect=lambda *_args, **_kwargs: _http_response(503)) as request, patch(
        "openaq.client._pace_sensor_history_request"
    ), patch("openaq.client.time.sleep") as sleep:
        try:
            fetch_sensor_measurements("test-key", 123, start, end)
        except requests.HTTPError:
            pass
        else:
            raise AssertionError("Expected HTTPError after bounded retries")

    assert request.call_count == MAX_HTTP_RETRIES + 1
    assert sleep.call_count == MAX_HTTP_RETRIES


def test_sensor_history_returns_parsed_data_after_transient_retry():
    start = datetime(2026, 9, 30, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=24)
    expected_rows = [{"value": 18.5, "period": {"label": "hour"}}]
    with patch(
        "openaq.client._SESSION.request",
        side_effect=[_http_response(502), _http_response(200, expected_rows)],
    ) as request, patch("openaq.client._pace_sensor_history_request"), patch(
        "openaq.client.time.sleep"
    ) as sleep:
        result = fetch_sensor_measurements("test-key", 123, start, end)

    assert result == expected_rows
    assert request.call_count == 2
    assert request.call_args.args[:2] == (
        "GET",
        f"{OPENAQ_BASE}/sensors/123/measurements",
    )
    assert sleep.call_count == 1
