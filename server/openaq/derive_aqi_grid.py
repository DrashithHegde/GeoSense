"""Derive CPCB AQI for GeoSense zones using OpenAQ measurements and IDW.

Replaces AQICN as the primary AQI ingestion path.
No destructive DB operations. Historical AQICN data preserved.

Freshness policy:
  fresh:       < 6 hours
  stale:       6-48 hours (accepted but labelled)
  unavailable: > 48 hours (rejected)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from statistics import mean
from typing import Dict, List, Optional, Tuple

from sqlalchemy import text

from app.database import get_db
from app.core.config import get_settings
from app.services.source_metadata import ensure_compatible_metadata, metadata_payload
from openaq.client import CPCB_PROVIDERS, get_mumbai_station_measurements
from openaq.cpcb_aqi import compute_station_cpcb_aqi
from aqicn.derive_aqi_grid import haversine_m

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

FRESH_THRESHOLD_HOURS = 6.0
STALE_THRESHOLD_HOURS = 48.0
PROVENANCE = "openaq_cpcb_idw"


def freshness_label(observed_at: datetime) -> str:
    age_h = (datetime.now(timezone.utc) - observed_at).total_seconds() / 3600
    if age_h < 0:
        return "unavailable"
    if age_h <= FRESH_THRESHOLD_HOURS:
        return "fresh"
    if age_h <= STALE_THRESHOLD_HOURS:
        return "stale"
    return "unavailable"


def select_idw_neighbors(
    zone_lat: float,
    zone_lon: float,
    points: List[Dict],
    k: int,
    max_interp_distance_m: float,
    min_stations: int,
    *,
    prefer_fresh: bool = True,
) -> List[Tuple[float, Dict]]:
    candidates = []
    for point in points:
        if point.get("freshness") == "unavailable":
            continue
        distance = haversine_m(zone_lat, zone_lon, point["lat"], point["lon"])
        if distance <= max_interp_distance_m:
            candidates.append((distance, point))
    fresh_candidates = [item for item in candidates if item[1].get("freshness") == "fresh"]
    if prefer_fresh and len(fresh_candidates) >= min_stations:
        candidates = fresh_candidates
    candidates.sort(key=lambda item: item[0])
    return candidates[:k]


def idw_estimate(
    zone_lat: float,
    zone_lon: float,
    points: List[Dict],
    k: int,
    max_interp_distance_m: float,
    min_stations: int,
    power: float,
    prefer_fresh: bool = True,
) -> Tuple[Optional[float], Optional[float], int]:
    selected = select_idw_neighbors(
        zone_lat,
        zone_lon,
        points,
        k,
        max_interp_distance_m,
        min_stations,
        prefer_fresh=prefer_fresh,
    )
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


def collect_station_aqi_points(
    *,
    max_age_hours: float = 48.0,
) -> Tuple[List[Dict], int, int]:
    """Collect the canonical real station inputs used by the AQI grid.

    This deliberately owns OpenAQ retrieval and CPCB conversion in one place so
    downstream derived products (such as a visualization surface) can consume
    the exact same station AQI semantics as the analytical-zone IDW pipeline.
    It performs no database writes.
    """
    api_key = get_settings().openaq_aqi_key
    if not api_key:
        raise RuntimeError("OPENAQ_AQI_KEY not configured")

    raw_stations = get_mumbai_station_measurements(
        api_key, max_age_hours=max_age_hours, cpcb_only=True
    )
    raw_stations = [station for station in raw_stations if station.get("is_cpcb_mpcb")]
    if not raw_stations:
        raise RuntimeError("OpenAQ returned no usable station measurements for MMR")

    station_points: List[Dict] = []
    cpcb_failures = 0
    for s in raw_stations:
        aqi_val, dominant, _sub_indices = compute_station_cpcb_aqi(s["pollutants"])
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
        })
        logger.info(
            "Station %s: CPCB AQI=%d dominant=%s freshness=%s provider=%s",
            s["station_name"], aqi_val, dominant,
            freshness_label(s["observed_at"]), s["provider"],
        )

    if not station_points:
        raise RuntimeError("No stations with computable CPCB AQI found")
    return station_points, len(raw_stations), cpcb_failures



def get_cell_points(db) -> list[dict]:
    sql = text("SELECT id, ST_X(centroid) AS lon, ST_Y(centroid) AS lat FROM spatial_cells ORDER BY id;")
    res = db.execute(sql)
    return [{"id": row[0], "lon": float(row[1]), "lat": float(row[2])} for row in res]

def upsert_openaq_aqi(
    db,
    cell_id: int,
    observed_at: datetime,
    aqi: Optional[int],
    source_type: Optional[str],
    nearest_dist_m: Optional[float],
    source_context: Optional[dict] = None,
):
    ensure_compatible_metadata(
        db, cell_id=cell_id, observed_at=observed_at, key="aqi", context=source_context,
    )
    db.execute(
        text(
            """
            INSERT INTO environment_data (
                cell_id, observed_at, aqi, aqi_source_type,
                aqi_nearest_station_distance_m, source_metadata
            )
            VALUES (:c, :obs, :aqi, :src, :dist, CAST(:metadata AS jsonb))
            ON CONFLICT (cell_id, observed_at)
            DO UPDATE SET
                aqi = EXCLUDED.aqi,
                aqi_source_type = EXCLUDED.aqi_source_type,
                aqi_nearest_station_distance_m = EXCLUDED.aqi_nearest_station_distance_m,
                source_metadata = environment_data.source_metadata || EXCLUDED.source_metadata
            """
        ),
        {
            "c": cell_id, "obs": observed_at,
            "aqi": int(round(aqi)) if aqi is not None else None,
            "src": source_type, "dist": nearest_dist_m,
            "metadata": metadata_payload("aqi", source_context),
        },
    )


def run_openaq_derivation(
    k: int = 4,
    max_interp_distance_m: float = 20000.0,
    min_stations: int = 2,
    power: float = 2.0,
    station_assign_distance_m: int = 8000,
    max_age_hours: float = 48.0,
    station_points: Optional[List[Dict]] = None,
    stations_fetched: Optional[int] = None,
    cpcb_aqi_failures: Optional[int] = None,
) -> Dict:
    """Fetch OpenAQ data, compute CPCB AQI, IDW to 189 zones.

    Raises RuntimeError if API key missing or no usable stations.
    Does NOT fall back to AQICN silently.
    """
    if station_points is None:
        station_points, stations_fetched, cpcb_aqi_failures = collect_station_aqi_points(
            max_age_hours=max_age_hours
        )
    allowed_providers = {provider.casefold() for provider in CPCB_PROVIDERS}
    station_points = [
        point for point in station_points
        if point.get("is_cpcb_mpcb")
        and str(point.get("provider", "")).casefold() in allowed_providers
        and point.get("freshness") != "unavailable"
    ]
    if not station_points:
        raise RuntimeError("No fresh or <=48-hour CPCB/MPCB stations with computable CPCB AQI found")
    if len(station_points) < min_stations:
        raise RuntimeError(
            f"Only {len(station_points)} eligible CPCB/MPCB stations; "
            f"at least {min_stations} are required for AQI interpolation"
        )
    if stations_fetched is None:
        stations_fetched = len(station_points)
    if cpcb_aqi_failures is None:
        cpcb_aqi_failures = 0

    observed_at = max(p["observed_at"] for p in station_points)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)

    source_context = {
        "source": "OpenAQ",
        "aqi_method": "CPCB_National_AQI_2014",
        "interpolation": "IDW",
        "provenance": PROVENANCE,
        "k": k, "power": power,
        "max_interpolation_distance_m": max_interp_distance_m,
        "minimum_stations": min_stations,
        "stations_used": len(station_points),
        "stations_cpcb_mpcb": sum(1 for p in station_points if p["is_cpcb_mpcb"]),
        "fallback_used": False,
    }

    with get_db() as db:
        cell_points = get_cell_points(db)
        observed_count = 0
        estimated_count = 0
        uncovered_count = 0
        aqi_vals = []
        sample_rows = []

        for z in cell_points:
            cid = int(z["id"])
            zlat = float(z["lat"])
            zlon = float(z["lon"])

            direct_candidates = []
            for point in station_points:
                dist = haversine_m(zlat, zlon, point["lat"], point["lon"])
                if dist <= min(station_assign_distance_m, 1000):
                    direct_candidates.append((dist, point))
            fresh_direct = [item for item in direct_candidates if item[1].get("freshness") == "fresh"]
            if fresh_direct:
                direct_candidates = fresh_direct
            direct = min(direct_candidates, key=lambda item: item[0]) if direct_candidates else None
            support_points: List[Tuple[float, Dict]] = []

            if direct is not None:
                aqi_val = direct[1]["aqi"]
                source_type = "openaq_observed"
                nearest = direct[0]
                support_points = [direct]
                observed_count += 1
            else:
                support_points = select_idw_neighbors(
                    zlat,
                    zlon,
                    station_points,
                    k,
                    max_interp_distance_m,
                    min_stations,
                    prefer_fresh=True,
                )
                est, nearest, used = idw_estimate(
                    zlat, zlon, station_points,
                    k=k, max_interp_distance_m=max_interp_distance_m,
                    min_stations=min_stations, power=power, prefer_fresh=True,
                )
                aqi_val = est
                if aqi_val is None:
                    source_type = None
                    uncovered_count += 1
                else:
                    source_type = PROVENANCE
                    estimated_count += 1

            if aqi_val is not None:
                aqi_vals.append(aqi_val)

            row_source_context = None
            if aqi_val is not None:
                row_source_context = {
                    **source_context,
                    "station_support": [
                        {
                            "station_id": point["station_id"],
                            "station_name": point["station_name"],
                            "provider": point["provider"],
                            "is_cpcb_mpcb": point["is_cpcb_mpcb"],
                            "pollutants": {
                                pollutant: {
                                    "sensor_id": metadata["sensor_id"],
                                    "source_unit": metadata["source_unit"],
                                    "normalized_unit": metadata["normalized_unit"],
                                    "averaging_period_hours": metadata["averaging_period_hours"],
                                }
                                for pollutant, metadata in point.get("pollutant_metadata", {}).items()
                            },
                        }
                        for _, point in support_points
                    ],
                }

            upsert_openaq_aqi(
                db, cid, observed_at,
                int(round(aqi_val)) if aqi_val is not None else None,
                source_type, nearest,
                source_context=row_source_context,
            )

            if len(sample_rows) < 15:
                sample_rows.append({
                    "cell_id": cid,
                    "aqi": int(round(aqi_val)) if aqi_val is not None else None,
                    "source_type": source_type,
                    "nearest_station_distance_m": round(nearest, 2) if nearest is not None else None,
                })

        db.commit()

    coverage = (observed_count + estimated_count) / len(cell_points) * 100.0 if cell_points else 0.0
    return {
        "source": "OpenAQ",
        "aqi_method": "CPCB_National_AQI_2014",
        "provenance": PROVENANCE,
        "stations_fetched": stations_fetched,
        "stations_with_cpcb_aqi": len(station_points),
        "stations_cpcb_mpcb": sum(1 for p in station_points if p["is_cpcb_mpcb"]),
        "cpcb_aqi_failures": cpcb_aqi_failures,
        "zones_total": len(cell_points),
        "zones_observed": observed_count,
        "zones_estimated": estimated_count,
        "zones_uncovered": uncovered_count,
        "coverage_percent": round(coverage, 2),
        "aqi_min": round(min(aqi_vals), 2) if aqi_vals else None,
        "aqi_max": round(max(aqi_vals), 2) if aqi_vals else None,
        "aqi_mean": round(mean(aqi_vals), 2) if aqi_vals else None,
        "observed_at": observed_at.isoformat(),
        "freshness": freshness_label(observed_at),
        "sample": sample_rows,
        "station_provenance": [
            {
                "station_id": point["station_id"],
                "station_name": point["station_name"],
                "provider": point["provider"],
                "is_cpcb_mpcb": point["is_cpcb_mpcb"],
                "aqi": point["aqi"],
                "dominant_pollutant": point["dominant_pollutant"],
                "observed_at": point["observed_at"].isoformat(),
                "freshness": point["freshness"],
                "pollutant_metadata": point.get("pollutant_metadata", {}),
            }
            for point in station_points
        ],
    }
