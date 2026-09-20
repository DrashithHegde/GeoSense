"""Tests for OpenAQ AQI ingestion and CPCB calculation."""
from datetime import datetime, timedelta, timezone

from openaq.client import CO_PPB_TO_UGM3
from openaq.cpcb_aqi import compute_station_cpcb_aqi, compute_pollutant_sub_indices
from openaq.derive_aqi_grid import freshness_label


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
