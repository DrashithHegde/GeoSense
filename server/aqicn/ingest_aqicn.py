"""Ingest AQICN station data and map to GeoSense zones.

Behavior:
- Fetch station measurements from AQICN using coordinates defined in
  `STATION_COORDS` (reusing legacy station list).
- Determine zone containing each station (ST_Contains). If none contains,
  optionally map to nearest zone within `max_distance_m` (default 5000m).
- Upsert measurements into `environment_data` with atomic INSERT...ON CONFLICT
  on `(zone_id, observed_at)`, updating only `aqi`, `pm25`, `pm10`, `no2`.
- Do NOT overwrite ndvi/ndwi or other fields.

Usage:
    python -m server.aqicn.ingest_aqicn

Environment:
    Set `AQICN_TOKEN` in your environment or server/.env (do NOT commit real token).
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Dict, List, Optional, Tuple

import requests
from sqlalchemy import text

from app.database import get_db
from app.core.config import get_settings
from app.services.source_metadata import ensure_compatible_metadata, metadata_payload
from scripts.fetch_mumbai_aqi import STATION_COORDS
from gee.gee_client import initialize_ee

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def parse_aqicn_time(time_obj: dict) -> Optional[datetime]:
    # AQICN may provide {'s': 'YYYY-MM-DD HH:MM:SS', 'tz': '+05:30'} or 'iso'
    if not time_obj:
        return None
    iso = time_obj.get("iso") or time_obj.get("s")
    tz = time_obj.get("tz")
    if not iso:
        return None
    try:
        # ``Z`` is accepted by current Python versions only after normalizing it.
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.strptime(str(iso), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

    if dt.tzinfo is None:
        offset = _parse_aqicn_offset(tz)
        # AQICN can omit a timezone.  UTC is the existing safe fallback, but a
        # supplied non-UTC offset is now converted rather than relabelled as UTC.
        dt = dt.replace(tzinfo=offset or timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_aqicn_offset(value: object) -> Optional[timezone]:
    if not value:
        return None
    match = re.fullmatch(r"([+-])(\d{1,2})(?::?(\d{2}))?", str(value).strip())
    if not match:
        return None
    sign, hours_text, minutes_text = match.groups()
    hours = int(hours_text)
    minutes = int(minutes_text or 0)
    if hours > 23 or minutes > 59:
        return None
    delta = timedelta(hours=hours, minutes=minutes)
    if sign == "-":
        delta = -delta
    return timezone(delta)


def _valid_aqi(value: object) -> bool:
    try:
        return 0 <= float(value) <= 500
    except (TypeError, ValueError):
        return False


def fetch_station_measurements(api_token: str) -> List[Dict]:
    """Discover Mumbai stations, then fetch each station by its AQICN UID.

    Geo probes can repeatedly resolve to one nearby/default feed. Station search
    preserves AQICN's actual station identity, coordinates, and source timestamp.
    Invalid AQI sentinel values such as 999 are excluded, not rewritten.
    """
    results: List[Dict] = []
    search = requests.get(
        "https://api.waqi.info/search/",
        params={"keyword": "Mumbai", "token": api_token},
        timeout=20,
    )
    search.raise_for_status()
    search_data = search.json()
    if search_data.get("status") != "ok":
        raise RuntimeError(f"AQICN station search failed: {search_data.get('data')}")

    discovered: dict[int, dict] = {}
    for item in search_data.get("data", []):
        station = item.get("station") or {}
        geo = station.get("geo") or []
        uid = item.get("uid")
        if uid is None or len(geo) != 2:
            continue
        lat, lon = float(geo[0]), float(geo[1])
        discovered[int(uid)] = {
            "station_name": station.get("name") or f"AQICN station {uid}",
            "station_uid": int(uid),
            "latitude": lat,
            "longitude": lon,
        }

    logger.info("AQICN station discovery returned %d unique stations", len(discovered))
    for station_info in discovered.values():
        uid = station_info["station_uid"]
        url = f"https://api.waqi.info/feed/@{uid}/"
        try:
            resp = requests.get(url, params={"token": api_token}, timeout=10)
            data = resp.json()
            if data.get("status") != "ok":
                logger.warning("AQICN response not ok for %s: %s", name, data.get("data"))
                continue
            d = data.get("data", {})
            iaqi = d.get("iaqi", {})
            time_obj = d.get("time", {})
            aqi = d.get("aqi")
            if not _valid_aqi(aqi):
                logger.info("Skipping %s uid=%s invalid AQI=%s", station_info["station_name"], uid, aqi)
                continue
            observed = parse_aqicn_time(time_obj)
            if observed is None:
                logger.warning("Skipping %s uid=%s because source timestamp is unavailable", station_info["station_name"], uid)
                continue

            results.append(
                {
                    **station_info,
                    "observed_at": observed,
                    "aqi": float(aqi),
                    "pm25": iaqi.get("pm25", {}).get("v"),
                    "pm10": iaqi.get("pm10", {}).get("v"),
                    "no2": iaqi.get("no2", {}).get("v"),
                }
            )
            logger.info(
                "Fetched station=%s uid=%s lat=%.6f lon=%.6f AQI=%s observed_at=%s",
                station_info["station_name"], uid, station_info["latitude"], station_info["longitude"], aqi, observed.isoformat(),
            )
        except Exception as e:
            logger.exception("Failed to fetch AQICN station uid=%s: %s", uid, e)
    return results


def map_station_to_zone(db, lon: float, lat: float, max_distance_m: int = 5000) -> Tuple[Optional[int], Optional[float], bool]:
    """Return (zone_id, distance_m, is_within) where is_within True if station inside zone."""
    # First try ST_Contains
    row = db.execute(
        text("SELECT id FROM zones WHERE ST_Contains(geometry, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)) LIMIT 1"),
        {"lon": lon, "lat": lat},
    ).fetchone()
    if row:
        return int(row[0]), 0.0, True

    # Else find nearest zone with distance (meters)
    nearest = db.execute(
        text(
            "SELECT id, ST_Distance(geometry::geography, ST_SetSRID(ST_MakePoint(:lon, :lat),4326)::geography) as dist_m "
            "FROM zones ORDER BY dist_m LIMIT 1"
        ),
        {"lon": lon, "lat": lat},
    ).fetchone()
    if not nearest:
        return None, None, False
    zone_id, dist_m = nearest[0], nearest[1]
    if dist_m is None:
        return None, None, False
    if dist_m <= max_distance_m:
        return int(zone_id), float(dist_m), False
    return None, float(dist_m), False


def upsert_measurement(
    db,
    zone_id: int,
    observed_at: datetime,
    aqi,
    pm25,
    pm10,
    no2,
    source_type: str,
    nearest_distance_m: float,
    source_context: Optional[dict] = None,
):
    # Atomic upsert, but only update the AQ columns (do not touch ndvi/ndwi)
    ensure_compatible_metadata(
        db,
        zone_id=zone_id,
        observed_at=observed_at,
        key="aqi",
        context=source_context,
    )
    db.execute(
        text(
            """
            INSERT INTO environment_data (
                zone_id, observed_at, aqi, pm25, pm10, no2,
                aqi_source_type, aqi_nearest_station_distance_m, source_metadata
            )
            VALUES (:z, :obs, :aqi, :pm25, :pm10, :no2, :src, :dist, CAST(:metadata AS jsonb))
            ON CONFLICT (zone_id, observed_at)
            DO UPDATE SET
                aqi = EXCLUDED.aqi,
                pm25 = EXCLUDED.pm25,
                pm10 = EXCLUDED.pm10,
                no2 = EXCLUDED.no2,
                aqi_source_type = EXCLUDED.aqi_source_type,
                aqi_nearest_station_distance_m = EXCLUDED.aqi_nearest_station_distance_m,
                source_metadata = environment_data.source_metadata || EXCLUDED.source_metadata
            """
        ),
        {
            "z": zone_id,
            "obs": observed_at,
            "aqi": aqi,
            "pm25": pm25,
            "pm10": pm10,
            "no2": no2,
            "src": source_type,
            "dist": nearest_distance_m,
            "metadata": metadata_payload("aqi", source_context),
        },
    )


def run_ingest(max_distance_m: int = 5000) -> Dict:
    api_token = get_settings().aqicn_token
    if not api_token:
        raise RuntimeError("AQICN_TOKEN not set in environment")

    initialize_ee()  # ensure credentials available (no GEE ops here but keep parity)

    stations = fetch_station_measurements(api_token)
    numeric_values = [float(s["aqi"]) for s in stations if s.get("aqi") is not None]
    logger.info(
        "Stations fetched: %d; AQI min=%s max=%s mean=%s unique=%d",
        len(stations), min(numeric_values) if numeric_values else None,
        max(numeric_values) if numeric_values else None,
        mean(numeric_values) if numeric_values else None,
        len(set(numeric_values)),
    )

    mapped = 0
    direct = 0
    estimated = 0
    stored = 0

    with get_db() as db:
        for s in stations:
            lon = s["longitude"]
            lat = s["latitude"]
            zone_id, dist_m, is_within = map_station_to_zone(db, lon, lat, max_distance_m=max_distance_m)
            if zone_id is None:
                logger.info("Station %s not mapped to any zone (nearest dist=%.1fm)", s["station_name"], dist_m or -1)
                continue
            mapped += 1
            if is_within:
                direct += 1
            else:
                estimated += 1

            observed_at = s["observed_at"]
            aqi = s.get("aqi")
            pm25 = s.get("pm25")
            pm10 = s.get("pm10")
            no2 = s.get("no2")
            source_context = (
                {
                    "source": "AQICN",
                    "method": "station_zone_mapping",
                    "station_assignment_max_distance_m": max_distance_m,
                }
                if any(value is not None for value in (aqi, pm25, pm10, no2))
                else None
            )

            source_type = "observed" if is_within else "estimated"
            upsert_measurement(
                db,
                zone_id,
                observed_at,
                aqi,
                pm25,
                pm10,
                no2,
                source_type=source_type,
                nearest_distance_m=float(dist_m or 0.0),
                source_context=source_context,
            )
            stored += 1

        db.commit()

    report = {
        "stations_fetched": len(stations),
        "stations_mapped": mapped,
        "direct_mapped": direct,
        "estimated_mapped": estimated,
        "stored": stored,
    }
    return report


if __name__ == "__main__":
    import sys

    try:
        report = run_ingest()
        logger.info("AQICN ingest report: %s", report)
        sys.exit(0)
    except Exception as e:
        logger.exception("AQICN ingest failed: %s", e)
        sys.exit(1)
