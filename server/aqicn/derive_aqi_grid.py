"""Derive AQI for all zones using IDW from AQICN station observations.

This script fetches current AQICN station observations, preserves directly
observed zones, and computes estimated AQI for uncovered zones via inverse
distance weighting (IDW).

It stores results in `environment_data` with atomic upsert and marks each row:
- `aqi_source_type = 'observed'` for zone containing a station
- `aqi_source_type = 'estimated'` for IDW-derived values

NDVI/NDWI fields are not touched.
"""
from __future__ import annotations

import argparse
import logging
import math
from datetime import datetime, timezone
from statistics import mean
from typing import Dict, List, Optional, Tuple

from sqlalchemy import text

from app.database import get_db
from app.core.config import get_settings
from app.services.source_metadata import ensure_compatible_metadata, metadata_payload
from aqicn.ingest_aqicn import fetch_station_measurements, map_station_to_zone

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def get_zone_points(db) -> List[Dict]:
    rows = db.execute(
        text(
            """
            SELECT id,
                   ST_X(ST_PointOnSurface(geometry)) AS lon,
                   ST_Y(ST_PointOnSurface(geometry)) AS lat
            FROM zones
            ORDER BY id
            """
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def aggregate_station_points(db, stations: List[Dict], station_assign_distance_m: int) -> Tuple[List[Dict], Dict[int, float], int]:
    """Map stations to zones; return mapped points and direct observed map for zones.

    mapped_points entries include station lat/lon and AQI value.
    direct_zone_values maps zone_id -> observed AQI (mean if multiple stations).
    """
    mapped_points: List[Dict] = []
    per_zone_observed: Dict[int, List[float]] = {}
    mumbai_near_count = 0

    for s in stations:
        zone_id, dist_m, is_within = map_station_to_zone(
            db,
            lon=float(s["longitude"]),
            lat=float(s["latitude"]),
            max_distance_m=station_assign_distance_m,
        )
        if zone_id is None:
            continue
        mumbai_near_count += 1
        aqi = s.get("aqi")
        if aqi is None:
            continue
        aqi_val = float(aqi)
        mapped_points.append(
            {
                "station_name": s["station_name"],
                "zone_id": zone_id,
                "lat": float(s["latitude"]),
                "lon": float(s["longitude"]),
                "aqi": aqi_val,
                "observed_at": s["observed_at"],
                "is_within": bool(is_within),
                "distance_m": float(dist_m or 0.0),
            }
        )
        if is_within:
            per_zone_observed.setdefault(zone_id, []).append(aqi_val)

    direct_zone_values = {zid: float(mean(vals)) for zid, vals in per_zone_observed.items() if vals}
    return mapped_points, direct_zone_values, mumbai_near_count


def idw_estimate(
    zone_lat: float,
    zone_lon: float,
    points: List[Dict],
    k: int,
    max_interp_distance_m: float,
    min_stations: int,
    power: float,
) -> Tuple[Optional[float], Optional[float], int]:
    dlist = []
    for p in points:
        d = haversine_m(zone_lat, zone_lon, p["lat"], p["lon"])
        if d <= max_interp_distance_m:
            dlist.append((d, p["aqi"]))
    if not dlist:
        return None, None, 0

    dlist.sort(key=lambda x: x[0])
    selected = dlist[:k]
    if len(selected) < min_stations:
        return None, None, len(selected)

    if selected[0][0] == 0:
        return float(selected[0][1]), 0.0, len(selected)

    weights = []
    vals = []
    for d, v in selected:
        w = 1.0 / (d**power)
        weights.append(w)
        vals.append(v)
    total_w = sum(weights)
    if total_w == 0:
        return None, None, len(selected)
    est = sum(w * v for w, v in zip(weights, vals)) / total_w
    return float(est), float(selected[0][0]), len(selected)


def upsert_aqi_grid(
    db,
    zone_id: int,
    observed_at: datetime,
    aqi: Optional[float],
    source_type: Optional[str],
    nearest_dist_m: Optional[float],
    source_context: Optional[dict] = None,
):
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
                zone_id, observed_at, aqi, aqi_source_type,
                aqi_nearest_station_distance_m, source_metadata
            )
            VALUES (:z, :obs, :aqi, :src, :dist, CAST(:metadata AS jsonb))
            ON CONFLICT (zone_id, observed_at)
            DO UPDATE SET
                aqi = EXCLUDED.aqi,
                aqi_source_type = EXCLUDED.aqi_source_type,
                aqi_nearest_station_distance_m = EXCLUDED.aqi_nearest_station_distance_m,
                source_metadata = environment_data.source_metadata || EXCLUDED.source_metadata
            """
        ),
        {
            "z": zone_id,
            "obs": observed_at,
            "aqi": int(round(aqi)) if aqi is not None else None,
            "src": source_type,
            "dist": nearest_dist_m,
            "metadata": metadata_payload("aqi", source_context),
        },
    )


def run_derivation(
    k: int,
    max_interp_distance_m: float,
    min_stations: int,
    power: float,
    station_assign_distance_m: int,
) -> Dict:
    token = get_settings().aqicn_token
    if not token:
        raise RuntimeError("AQICN_TOKEN not set")

    stations = fetch_station_measurements(token)
    with get_db() as db:
        zone_points = get_zone_points(db)
        mapped_points, direct_zone_values, mumbai_near_count = aggregate_station_points(
            db, stations, station_assign_distance_m=station_assign_distance_m
        )
        if not mapped_points:
            raise RuntimeError("No usable AQICN stations mapped near Mumbai zones; cannot derive grid AQI")

        observed_at = max(p["observed_at"] for p in mapped_points)
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        else:
            observed_at = observed_at.astimezone(timezone.utc)

        observed_count = 0
        estimated_count = 0
        uncovered_count = 0
        aqi_vals = []
        sample_rows = []
        source_context = {
            "source": "AQICN",
            "method": "station_discovery_idw",
            "k": k,
            "power": power,
            "max_interpolation_distance_m": max_interp_distance_m,
            "minimum_stations": min_stations,
            "station_assignment_max_distance_m": station_assign_distance_m,
            "fallback_used": False,
        }

        for z in zone_points:
            zid = int(z["id"])
            zlat = float(z["lat"])
            zlon = float(z["lon"])

            if zid in direct_zone_values:
                aqi_val = direct_zone_values[zid]
                source_type = "observed"
                nearest = 0.0
                observed_count += 1
                used = 1
            else:
                est, nearest, used = idw_estimate(
                    zlat,
                    zlon,
                    mapped_points,
                    k=k,
                    max_interp_distance_m=max_interp_distance_m,
                    min_stations=min_stations,
                    power=power,
                )
                aqi_val = est
                if aqi_val is None:
                    source_type = None
                    uncovered_count += 1
                else:
                    source_type = "estimated"
                    estimated_count += 1

            if aqi_val is not None:
                aqi_vals.append(aqi_val)

            upsert_aqi_grid(
                db,
                zid,
                observed_at,
                aqi_val,
                source_type,
                nearest,
                source_context=source_context if aqi_val is not None else None,
            )

            if len(sample_rows) < 15:
                sample_rows.append(
                    {
                        "zone_id": zid,
                        "aqi": int(round(aqi_val)) if aqi_val is not None else None,
                        "source_type": source_type,
                        "nearest_station_distance_m": round(nearest, 2) if nearest is not None else None,
                    }
                )

        db.commit()

    coverage = (observed_count + estimated_count) / len(zone_points) * 100.0 if zone_points else 0.0
    return {
        "stations_discovered": len(stations),
        "stations_near_mumbai": mumbai_near_count,
        "zones_total": len(zone_points),
        "zones_observed": observed_count,
        "zones_estimated": estimated_count,
        "zones_uncovered": uncovered_count,
        "coverage_percent": round(coverage, 2),
        "aqi_min": round(min(aqi_vals), 2) if aqi_vals else None,
        "aqi_max": round(max(aqi_vals), 2) if aqi_vals else None,
        "aqi_mean": round(mean(aqi_vals), 2) if aqi_vals else None,
        "observed_at": observed_at.isoformat(),
        "sample": sample_rows,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--k", type=int, default=4, help="Number of nearest stations for IDW")
    p.add_argument("--max-distance-m", type=float, default=15000.0, help="Max interpolation distance in meters")
    p.add_argument("--min-stations", type=int, default=2, help="Minimum stations required for IDW")
    p.add_argument("--power", type=float, default=2.0, help="IDW power parameter")
    p.add_argument(
        "--station-assign-distance-m",
        type=int,
        default=8000,
        help="Max distance for considering station near Mumbai zones",
    )
    return p.parse_args()


if __name__ == "__main__":
    import sys

    args = parse_args()
    try:
        report = run_derivation(
            k=args.k,
            max_interp_distance_m=args.max_distance_m,
            min_stations=args.min_stations,
            power=args.power,
            station_assign_distance_m=args.station_assign_distance_m,
        )
        logger.info("AQI grid derivation report: %s", report)
        logger.info("Sample zone AQI rows:")
        for row in report["sample"]:
            logger.info("zone_id=%s aqi=%s source_type=%s nearest_station_distance=%s", row["zone_id"], row["aqi"], row["source_type"], row["nearest_station_distance_m"])
        sys.exit(0)
    except Exception as exc:
        logger.exception("AQI derivation failed: %s", exc)
        sys.exit(1)
