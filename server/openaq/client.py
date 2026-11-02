"""OpenAQ v3 API client for GeoSense AQI ingestion.

Discovers Mumbai/MMR stations and fetches latest pollutant measurements.
Never fabricates missing measurements.
Provider/source label preserved for CPCB/MPCB provenance.
"""
from __future__ import annotations

import logging
import math
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta, timezone
import time
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

MMR_BBOX = "72.77,18.89,73.12,19.40"
CPCB_PROVIDERS = {"CPCB", "caaqm", "MPCB", "BMC"}
AQI_POLLUTANTS = {"pm25", "pm10", "no2", "so2", "o3", "co"}
POLLUTANT_AVERAGING_HOURS = {
    "pm25": 24,
    "pm10": 24,
    "no2": 24,
    "so2": 24,
    "o3": 8,
    "co": 8,
}
MIN_COVERAGE_HOURS = {24: 16.0, 8: 6.0}
GAS_MOLECULAR_WEIGHTS = {"no2": 46.0055, "so2": 64.066, "o3": 47.9982}
CO_PPB_TO_UGM3 = 1.145
OPENAQ_BASE = "https://api.openaq.org/v3"
REQUEST_TIMEOUT = 20
MEASUREMENT_PAGE_SIZE = 1000
MAX_MEASUREMENT_PAGES = 10
MAX_HTTP_RETRIES = 3
HTTP_BACKOFF_BASE_SECONDS = 0.5
HTTP_BACKOFF_MAX_SECONDS = 8.0
SENSOR_REQUEST_INTERVAL_SECONDS = 0.2
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_SESSION = requests.Session()
_last_sensor_request_at: float | None = None


def _headers(api_key: str) -> Dict[str, str]:
    return {"X-API-Key": api_key}


def _retry_delay(response: requests.Response, retry_number: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            delay = float(retry_after)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(retry_after)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                delay = (retry_at - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                delay = -1.0
        if delay >= 0:
            return delay
    return min(HTTP_BACKOFF_BASE_SECONDS * (2 ** retry_number), HTTP_BACKOFF_MAX_SECONDS)


def _request(method: str, url: str, **kwargs: Any) -> requests.Response:
    for retry_number in range(MAX_HTTP_RETRIES + 1):
        response = _SESSION.request(method, url, **kwargs)
        if response.status_code not in RETRYABLE_STATUS_CODES or retry_number == MAX_HTTP_RETRIES:
            response.raise_for_status()
            return response
        delay = _retry_delay(response, retry_number)
        response.close()
        time.sleep(delay)
    raise RuntimeError("OpenAQ request retry loop ended unexpectedly")


def _pace_sensor_history_request() -> None:
    global _last_sensor_request_at
    now = time.monotonic()
    if _last_sensor_request_at is not None:
        delay = SENSOR_REQUEST_INTERVAL_SECONDS - (now - _last_sensor_request_at)
        if delay > 0:
            time.sleep(delay)
    _last_sensor_request_at = time.monotonic()


def discover_mmr_stations(api_key: str) -> List[Dict[str, Any]]:
    """Return OpenAQ location dicts within the MMR bounding box."""
    url = f"{OPENAQ_BASE}/locations"
    params = {"bbox": MMR_BBOX, "limit": 200}
    resp = _request("GET", url, params=params, headers=_headers(api_key), timeout=REQUEST_TIMEOUT)
    data = resp.json()
    stations = []
    for loc in data.get("results", []):
        coords = loc.get("coordinates") or {}
        lat = coords.get("latitude")
        lon = coords.get("longitude")
        if lat is None or lon is None:
            continue
        provider_name = (loc.get("provider") or {}).get("name", "Unknown").strip()
        cpcb_mpcb_providers = {name.casefold() for name in CPCB_PROVIDERS}
        stations.append(
            {
                "id": loc["id"],
                "name": loc.get("name", f"OpenAQ-{loc['id']}"),
                "latitude": float(lat),
                "longitude": float(lon),
                "provider": provider_name,
                "is_cpcb_mpcb": provider_name.casefold() in cpcb_mpcb_providers,
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


def _format_utc_dt(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def within_freshness_window(
    observed_at: datetime,
    *,
    now: datetime | None = None,
    max_age_hours: float = 48.0,
) -> bool:
    current = now or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    age_hours = (current - observed_at.astimezone(timezone.utc)).total_seconds() / 3600
    return 0.0 <= age_hours <= max_age_hours


def normalize_concentration(value: float, units: str, pollutant: str) -> Optional[float]:
    """Normalize supported OpenAQ units to the CPCB calculator's ug/m3 input."""
    try:
        concentration = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(concentration) or concentration < 0:
        return None

    unit = (units or "").strip().lower()
    unit = unit.replace("μ", "µ").replace("³", "3").replace("^", "").replace(" ", "")
    if unit in {"µg/m3", "ug/m3", "microgram/m3", "micrograms/m3"}:
        return concentration
    if unit == "mg/m3":
        return concentration * 1000.0
    if unit == "ng/m3":
        return concentration / 1000.0

    if unit in {"ppb", "partsperbillion"}:
        scale = 1.0
    elif unit in {"ppm", "partspermillion"}:
        scale = 1000.0
    else:
        return None
    if pollutant == "co":
        factor = CO_PPB_TO_UGM3
    else:
        molecular_weight = GAS_MOLECULAR_WEIGHTS.get(pollutant)
        if molecular_weight is None:
            return None
        factor = molecular_weight / 24.45
    return concentration * factor * scale


def _measurement_interval(measurement: Dict[str, Any]) -> tuple[datetime, datetime] | None:
    period = measurement.get("period") or {}
    coverage = measurement.get("coverage") or {}
    start = _parse_utc_dt(coverage.get("datetimeFrom") or period.get("datetimeFrom"))
    end = _parse_utc_dt(coverage.get("datetimeTo") or period.get("datetimeTo"))
    if start is None or end is None or end <= start:
        return None
    return start, end


def _weighted_window_average(
    samples: list[tuple[datetime, datetime, float, float]],
    window_start: datetime,
    window_end: datetime,
    minimum_coverage_hours: float,
) -> dict[str, Any] | None:
    window_start = window_start.astimezone(timezone.utc)
    window_end = window_end.astimezone(timezone.utc)
    intervals = []
    for start, end, normalized_value, raw_value in samples:
        clipped_start = max(start, window_start)
        clipped_end = min(end, window_end)
        if clipped_end > clipped_start:
            intervals.append((clipped_start, clipped_end, normalized_value, raw_value))
    intervals.sort(key=lambda item: (item[0], item[1]))

    cursor = window_start
    weighted_normalized = 0.0
    weighted_raw = 0.0
    covered_seconds = 0.0
    sample_count = 0
    latest_end = None
    for start, end, normalized_value, raw_value in intervals:
        start = max(start, cursor)
        if end <= start:
            continue
        duration = (end - start).total_seconds()
        weighted_normalized += normalized_value * duration
        weighted_raw += raw_value * duration
        covered_seconds += duration
        sample_count += 1
        cursor = end
        latest_end = end if latest_end is None else max(latest_end, end)

    coverage_hours = covered_seconds / 3600.0
    if coverage_hours + 1e-6 < minimum_coverage_hours or covered_seconds <= 0:
        return None
    return {
        "normalized_value": weighted_normalized / covered_seconds,
        "raw_average": weighted_raw / covered_seconds,
        "sample_count": sample_count,
        "coverage_hours": coverage_hours,
        "observed_at": latest_end,
        "window_start": window_start,
        "window_end": window_end,
    }


def aggregate_sensor_measurements(
    measurements: list[Dict[str, Any]],
    *,
    pollutant: str,
    units: str,
    window_start: datetime,
    window_end: datetime,
    max_age_hours: float = 48.0,
) -> dict[str, Any] | None:
    """Aggregate the latest completed, fresh CPCB averaging period.

    PM2.5, PM10, NO2, and SO2 use a 24-hour time-weighted mean with at least
    16 covered hours. O3 and CO use the highest supported rolling 8-hour mean
    in the 24 hours ending at the latest valid observation, with at least 6
    covered hours. Observations outside the freshness window are excluded.
    """
    averaging_hours = POLLUTANT_AVERAGING_HOURS.get(pollutant)
    if averaging_hours is None:
        return None
    reference_time = window_end.astimezone(timezone.utc)
    samples = []
    for measurement in measurements:
        if (measurement.get("flagInfo") or {}).get("hasFlags"):
            continue
        value = measurement.get("value")
        interval = _measurement_interval(measurement)
        if value is None or interval is None:
            continue
        if not within_freshness_window(
            interval[1], now=reference_time, max_age_hours=max_age_hours
        ):
            continue
        normalized = normalize_concentration(value, units, pollutant)
        if normalized is None:
            continue
        samples.append((interval[0], interval[1], normalized, float(value)))
    if not samples:
        return None

    latest_observation_end = max(sample[1] for sample in samples)
    if averaging_hours == 24:
        period_start = latest_observation_end - timedelta(hours=24)
        average = _weighted_window_average(
            samples, period_start, latest_observation_end, MIN_COVERAGE_HOURS[24]
        )
        if average is not None:
            average["averaging_period_hours"] = 24
        return average

    best = None
    search_start = max(
        window_start.astimezone(timezone.utc),
        latest_observation_end - timedelta(hours=24),
    )
    end = latest_observation_end
    first_end = search_start + timedelta(hours=averaging_hours)
    while end >= first_end:
        start = end - timedelta(hours=averaging_hours)
        average = _weighted_window_average(samples, start, end, MIN_COVERAGE_HOURS[8])
        if average is not None and (
            best is None
            or average["normalized_value"] > best["normalized_value"]
            or (average["normalized_value"] == best["normalized_value"] and average["window_end"] > best["window_end"])
        ):
            best = average
        end -= timedelta(hours=1)
    if best is not None:
        best["averaging_period_hours"] = 8
    return best


def _build_sensor_map(sensors: List[Dict]) -> Dict[int, Dict]:
    m: Dict[int, Dict] = {}
    for s in sensors:
        sid = s.get("id")
        param = s.get("parameter") or {}
        if sid is not None:
            m[int(sid)] = {
                "param_name": param.get("name", ""),
                "units": param.get("units", ""),
                "parameter_id": param.get("id"),
            }
    return m


def fetch_latest_measurements(api_key: str, location_id: int) -> List[Dict[str, Any]]:
    url = f"{OPENAQ_BASE}/locations/{location_id}/latest"
    resp = _request("GET", url, headers=_headers(api_key), timeout=REQUEST_TIMEOUT)
    return resp.json().get("results", [])


def fetch_sensor_measurements(
    api_key: str,
    sensor_id: int,
    window_start: datetime,
    window_end: datetime,
) -> List[Dict[str, Any]]:
    """Fetch OpenAQ v3 period measurements for one sensor and time window."""
    url = f"{OPENAQ_BASE}/sensors/{sensor_id}/measurements"
    results: List[Dict[str, Any]] = []
    for page in range(1, MAX_MEASUREMENT_PAGES + 1):
        _pace_sensor_history_request()
        response = _request(
            "GET",
            url,
            params={
                "datetime_from": _format_utc_dt(window_start),
                "datetime_to": _format_utc_dt(window_end),
                "limit": MEASUREMENT_PAGE_SIZE,
                "page": page,
            },
            headers=_headers(api_key),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        rows = response.json().get("results", [])
        results.extend(rows)
        if len(rows) < MEASUREMENT_PAGE_SIZE:
            break
    return results


def collect_station_pollutants(
    api_key: str,
    station: Dict[str, Any],
    max_age_hours: float = 48.0,
) -> Optional[Dict[str, Any]]:
    """Fetch sensor history and derive period-averaged pollutant concentrations."""
    sensors_meta = _build_sensor_map(station.get("sensors", []))
    window_end = datetime.now(timezone.utc)
    max_averaging_hours = max(POLLUTANT_AVERAGING_HOURS.values())
    window_start = window_end - timedelta(hours=max_age_hours + max_averaging_hours)
    candidates: Dict[str, List[Dict[str, Any]]] = {}
    for sensor_id, sensor_info in sensors_meta.items():
        param_name = sensor_info["param_name"]
        if param_name not in AQI_POLLUTANTS:
            continue
        try:
            measurements = fetch_sensor_measurements(api_key, sensor_id, window_start, window_end)
        except Exception as exc:
            logger.warning("OpenAQ: failed sensor history for sensor_id=%s: %s", sensor_id, exc)
            continue
        aggregate = aggregate_sensor_measurements(
            measurements,
            pollutant=param_name,
            units=sensor_info["units"],
            window_start=window_start,
            window_end=window_end,
            max_age_hours=max_age_hours,
        )
        if aggregate is None:
            continue
        aggregate.update({
            "sensor_id": sensor_id,
            "parameter_id": sensor_info["parameter_id"],
            "source_unit": sensor_info["units"],
            "normalized_unit": "µg/m³",
        })
        candidates.setdefault(param_name, []).append(aggregate)

    pollutants: Dict[str, float] = {}
    pollutant_metadata: Dict[str, Dict[str, Any]] = {}
    timestamps: List[datetime] = []
    for param_name, sensor_candidates in candidates.items():
        selected = max(
            sensor_candidates,
            key=lambda item: (item["coverage_hours"], item["observed_at"], -item["sensor_id"]),
        )
        pollutants[param_name] = float(selected["normalized_value"])
        pollutant_metadata[param_name] = {
            "sensor_id": selected["sensor_id"],
            "parameter_id": selected["parameter_id"],
            "source_unit": selected["source_unit"],
            "raw_average": selected["raw_average"],
            "normalized_value_ugm3": selected["normalized_value"],
            "normalized_unit": selected["normalized_unit"],
            "averaging_period_hours": selected["averaging_period_hours"],
            "coverage_hours": round(selected["coverage_hours"], 3),
            "sample_count": selected["sample_count"],
            "window_start": _format_utc_dt(selected["window_start"]),
            "window_end": _format_utc_dt(selected["window_end"]),
            "observed_at": _format_utc_dt(selected["observed_at"]),
        }
        timestamps.append(selected["observed_at"])

    if not timestamps:
        return None
    observed_at = min(timestamps)
    if not within_freshness_window(
        observed_at, max_age_hours=max_age_hours, now=window_end
    ):
        return None

    return {
        "station_id": station["id"],
        "station_name": station["name"],
        "latitude": station["latitude"],
        "longitude": station["longitude"],
        "provider": station["provider"],
        "is_cpcb_mpcb": station["is_cpcb_mpcb"],
        "observed_at": observed_at,
        "pollutants": pollutants,
        "pollutant_metadata": pollutant_metadata,
    }


def get_mumbai_station_measurements(
    api_key: str,
    max_age_hours: float = 48.0,
    cpcb_only: bool = True,
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
