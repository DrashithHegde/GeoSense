"""OpenAQ v3 API client for GeoSense AQI ingestion.

Discovers Mumbai/MMR stations and fetches latest pollutant measurements.
Never fabricates missing measurements.
Provider/source label preserved for CPCB/MPCB provenance.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

MMR_BBOX = "72.77,18.89,73.12,19.40"
CPCB_PROVIDERS = {"CPCB", "caaqm", "MPCB", "BMC"}
AQI_POLLUTANTS = {"pm25", "pm10", "no2", "so2", "o3", "co"}
CO_PPB_TO_UGM3 = 1.145
OPENAQ_BASE = "https://api.openaq.org/v3"
REQUEST_TIMEOUT = 20


def _headers(api_key: str) -> Dict[str, str]:
    return {"X-API-Key": api_key}


def discover_mmr_stations(api_key: str) -> List[Dict[str, Any]]:
    """Return OpenAQ location dicts within the MMR bounding box."""
    url = f"{OPENAQ_BASE}/locations"
    params = {"bbox": MMR_BBOX, "limit": 200}
    resp = requests.get(url, params=params, headers=_headers(api_key), timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    stations = []
    for loc in data.get("results", []):
        coords = loc.get("coordinates") or {}
        lat = coords.get("latitude")
        lon = coords.get("longitude")
        if lat is None or lon is None:
            continue
        provider_name = (loc.get("provider") or {}).get("name", "Unknown")
        stations.append(
            {
                "id": loc["id"],
                "name": loc.get("name", f"OpenAQ-{loc['id']}"),
                "latitude": float(lat),
                "longitude": float(lon),
                "provider": provider_name,
                "is_cpcb_mpcb": provider_name in CPCB_PROVIDERS,
                "sensors": loc.get("sensors") or [],
            }
        )
    logger.info(
        "OpenAQ: discovered %d stations in MMR bbox (%d CPCB/MPCB-backed)",
        len(stations), sum(1 for s in stations if s["is_cpcb_mpcb"]),
    )
    return stations


def _parse_utc_dt(dt_obj: Any) -> Optional[datetime]:
    if not dt_obj:
        return None
    utc_str = dt_obj.get("utc") if isinstance(dt_obj, dict) else str(dt_obj)
    if not utc_str:
        return None
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return None


def _build_sensor_map(sensors: List[Dict]) -> Dict[int, Dict]:
    m: Dict[int, Dict] = {}
    for s in sensors:
        sid = s.get("id")
        param = s.get("parameter") or {}
        if sid is not None:
            m[int(sid)] = {"param_name": param.get("name", ""), "units": param.get("units", "")}
    return m


def fetch_latest_measurements(api_key: str, location_id: int) -> List[Dict[str, Any]]:
    url = f"{OPENAQ_BASE}/locations/{location_id}/latest"
    resp = requests.get(url, headers=_headers(api_key), timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json().get("results", [])


def collect_station_pollutants(
    api_key: str,
    station: Dict[str, Any],
    max_age_hours: float = 48.0,
) -> Optional[Dict[str, Any]]:
    """Fetch and aggregate pollutant concentrations for one station.

    Returns dict with station metadata + pollutants dict, or None if no fresh data.
    Pollutants missing from the station are absent from the dict (no fabrication).
    """
    location_id = station["id"]
    sensors_meta = _build_sensor_map(station.get("sensors", []))
    try:
        raw = fetch_latest_measurements(api_key, location_id)
    except Exception as exc:
        logger.warning("OpenAQ: failed to fetch location_id=%s: %s", location_id, exc)
        return None

    pollutants: Dict[str, float] = {}
    timestamps: List[datetime] = []

    for meas in raw:
        sensor_id = meas.get("sensorsId")
        value = meas.get("value")
        dt_obj = meas.get("datetime")
        if sensor_id is None or value is None:
            continue
        sensor_info = sensors_meta.get(int(sensor_id), {})
        param_name = sensor_info.get("param_name", "").lower()
        units = sensor_info.get("units", "").lower()
        if param_name not in AQI_POLLUTANTS:
            continue
        observed_at = _parse_utc_dt(dt_obj)
        if observed_at is None:
            continue
        age_hours = (datetime.now(timezone.utc) - observed_at).total_seconds() / 3600
        if age_hours > max_age_hours:
            continue
        v = float(value)
        if param_name == "co" and "ppb" in units:
            v = v * CO_PPB_TO_UGM3
        # Prefer ug/m3; accept ppb for non-CO if no ug/m3 available
        if "µg/m" in units or "ug/m" in units:
            pollutants[param_name] = v
            timestamps.append(observed_at)
        elif param_name not in pollutants and param_name != "co":
            pollutants[param_name] = v
            timestamps.append(observed_at)

    if not timestamps:
        return None

    return {
        "station_id": location_id,
        "station_name": station["name"],
        "latitude": station["latitude"],
        "longitude": station["longitude"],
        "provider": station["provider"],
        "is_cpcb_mpcb": station["is_cpcb_mpcb"],
        "observed_at": max(timestamps),
        "pollutants": pollutants,
    }


def get_mumbai_station_measurements(
    api_key: str,
    max_age_hours: float = 48.0,
    cpcb_only: bool = False,
) -> List[Dict[str, Any]]:
    """Discover stations + collect pollutant data. Returns list of station dicts."""
    stations = discover_mmr_stations(api_key)
    if cpcb_only:
        stations = [s for s in stations if s["is_cpcb_mpcb"]]
        logger.info("OpenAQ: filtering to %d CPCB/MPCB stations", len(stations))
    results = []
    for station in stations:
        data = collect_station_pollutants(api_key, station, max_age_hours=max_age_hours)
        if data and data.get("pollutants"):
            results.append(data)
    logger.info(
        "OpenAQ: %d/%d stations returned usable measurements",
        len(results), len(stations),
    )
    return results
