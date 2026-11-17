"""CPCB AQI per station from OpenAQ measurements (the input of the AQI surface).

    OpenAQ v3 -> CPCB-network stations around the city in use -> CPCB National AQI (2014)

The surface itself (IDW, GeoTIFF, map images) is built by
app/services/surfaces/aqi_station_surface.py from these station points.

Freshness policy:
  fresh:       < 6 hours
  stale:       6-48 hours (accepted but labelled)
  unavailable: > 48 hours (rejected)
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from app.core.config import get_settings
from openaq.client import get_station_measurements
from openaq.cpcb_aqi import compute_station_cpcb_aqi

logger = logging.getLogger(__name__)

FRESH_THRESHOLD_HOURS = 6.0
STALE_THRESHOLD_HOURS = 48.0
PROVENANCE = "openaq_cpcb_idw"


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def freshness_label(observed_at: datetime) -> str:
    age_h = (datetime.now(timezone.utc) - observed_at).total_seconds() / 3600
    if age_h < 0:
        return "unavailable"
    if age_h <= FRESH_THRESHOLD_HOURS:
        return "fresh"
    if age_h <= STALE_THRESHOLD_HOURS:
        return "stale"
    return "unavailable"


def select_idw_neighbors(lat: float, lon: float, points: List[Dict], k: int, max_interp_distance_m: float,
                         min_stations: int, *, prefer_fresh: bool = True) -> List[Tuple[float, Dict]]:
    candidates = []
    for point in points:
        if point.get("freshness") == "unavailable":
            continue
        distance = haversine_m(lat, lon, point["lat"], point["lon"])
        if distance <= max_interp_distance_m:
            candidates.append((distance, point))
    fresh_candidates = [item for item in candidates if item[1].get("freshness") == "fresh"]
    if prefer_fresh and len(fresh_candidates) >= min_stations:
        candidates = fresh_candidates
    candidates.sort(key=lambda item: item[0])
    return candidates[:k]


def idw_estimate(lat: float, lon: float, points: List[Dict], k: int, max_interp_distance_m: float,
                 min_stations: int, power: float, prefer_fresh: bool = True) -> Tuple[Optional[float], Optional[float], int]:
    selected = select_idw_neighbors(lat, lon, points, k, max_interp_distance_m, min_stations,
                                    prefer_fresh=prefer_fresh)
    if not selected:
        return None, None, 0
    if len(selected) < min_stations:
        return None, None, len(selected)
    if selected[0][0] == 0:
        return float(selected[0][1]["aqi"]), 0.0, len(selected)
    weights = [1.0 / (distance ** power) for distance, _ in selected]
    vals = [point["aqi"] for _, point in selected]
    total_w = sum(weights)
    if total_w == 0:
        return None, None, len(selected)
    est = sum(w * v for w, v in zip(weights, vals)) / total_w
    return float(est), float(selected[0][0]), len(selected)


def collect_station_aqi_points(*, max_age_hours: float = 48.0) -> Tuple[List[Dict], int, int]:
    """Real station inputs for the AQI surface of the current city: OpenAQ retrieval and CPCB
    conversion in one place. No database writes."""
    from app.core.cities import get_city

    api_key = get_settings().openaq_aqi_key
    if not api_key:
        raise RuntimeError("OPENAQ_AQI_KEY not configured")

    raw_stations = get_station_measurements(api_key, max_age_hours=max_age_hours, cpcb_only=True)
    raw_stations = [station for station in raw_stations if station.get("is_cpcb_mpcb")]
    if not raw_stations:
        raise RuntimeError(f"OpenAQ returned no usable CPCB-network station measurements around {get_city().name}")

    station_points: List[Dict] = []
    cpcb_failures = 0
    for s in raw_stations:
        aqi_val, dominant, sub_indices = compute_station_cpcb_aqi(s["pollutants"])
        if aqi_val is None:
            cpcb_failures += 1
            continue
        station_points.append({
            "station_id": s["station_id"],
            "station_name": s["station_name"],
            "lat": s["latitude"],
            "lon": s["longitude"],
            "provider": s["provider"],
            "is_cpcb_mpcb": s["is_cpcb_mpcb"],
            "aqi": float(aqi_val),
            "dominant_pollutant": dominant,
            "observed_at": s["observed_at"],
            "freshness": freshness_label(s["observed_at"]),
            "pollutant_metadata": s.get("pollutant_metadata", {}),
            "sub_indices": {k: (None if v is None else round(float(v), 1)) for k, v in sub_indices.items()},
        })
        logger.info("Station %s: CPCB AQI=%d dominant=%s freshness=%s provider=%s",
                    s["station_name"], aqi_val, dominant, freshness_label(s["observed_at"]), s["provider"])

    if not station_points:
        raise RuntimeError("No stations with computable CPCB AQI found")
    return station_points, len(raw_stations), cpcb_failures
