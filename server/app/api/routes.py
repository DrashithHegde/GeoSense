from typing import Optional
import json
from functools import lru_cache
import requests
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

from sqlalchemy import text, select, func
from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends
from pydantic import BaseModel

router = APIRouter()

from app.database import engine
from app.database import get_db
from app.models import Zone, EnvironmentData, AnomalyResult
from app.services.feature_anomaly_pipeline import run_feature_anomaly_pipeline
from app.services.operational_status import get_operational_status
from app.services.explanation_evidence import (
    build_zone_evidence,
    ZoneNotFoundError,
    NoAnomalyResultError,
)
from app.services.explanation_engine import generate_deterministic_explanation
from app.services.explanation_service import build_full_explanation
from app.services.composite_score import calculate_composite
from app.services.municipality_aggregation import get_municipality_metrics
from app.services.water_bodies import get_water_bodies_with_health
from app.services.surfaces.aqi_surface import load_latest_aqi_surface
from app.services.surfaces.ndvi_surface import load_latest_ndvi_surface
from app.services.surfaces.lst_surface import load_latest_lst_surface
from datetime import datetime, timedelta


def _fetch_all(query: str, params: dict | None = None):
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query), params or {})
            return [dict(row) for row in result.mappings().all()]
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database query failed: {exc}") from exc


def _execute(query: str, params: dict | None = None):
    try:
        with engine.begin() as conn:
            conn.execute(text(query), params or {})
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database operation failed: {exc}") from exc


@router.get("/metrics/latest")
async def get_latest_metrics(db_cm = Depends(get_db)):
    with db_cm as db:
        # Each source has its own cadence. A global max(observed_at) would drop
        # valid AQI/LST values whenever a newer satellite composite exists.
        stmt = text(
            """
            WITH latest_aqi AS (
                SELECT DISTINCT ON (zone_id) *
                FROM environment_data
                WHERE aqi IS NOT NULL
                ORDER BY zone_id,
                         CASE WHEN source_metadata->'aqi'->>'method' = 'station_discovery_idw' THEN 0 ELSE 1 END,
                         observed_at DESC, id DESC
            ), latest_ndvi AS (
                SELECT DISTINCT ON (zone_id) *
                FROM environment_data
                WHERE ndvi IS NOT NULL
                ORDER BY zone_id, observed_at DESC, id DESC
            ), latest_lst AS (
                SELECT DISTINCT ON (zone_id) *
                FROM environment_data
                WHERE lst IS NOT NULL
                ORDER BY zone_id, observed_at DESC, id DESC
            ), latest_water AS (
                SELECT DISTINCT ON (zone_id) *
                FROM environment_data
                WHERE mndwi IS NOT NULL
                ORDER BY zone_id, observed_at DESC, id DESC
            )
            SELECT
                z.id,
                z.name,
                z.ward,
                ST_X(ST_Centroid(z.geometry)) AS longitude,
                ST_Y(ST_Centroid(z.geometry)) AS latitude,
                ST_AsGeoJSON(z.geometry) AS geometry_geojson,
                ndvi.ndvi,
                ndvi.ndwi,
                ndvi.observed_at AS ndvi_observed_at,
                ndvi.source_metadata AS ndvi_source_metadata,
                lst.lst,
                lst.observed_at AS lst_observed_at,
                lst.source_metadata AS lst_source_metadata,
                water.mndwi,
                water.ndci,
                water.turbidity_proxy,
                water.water_extent_m2,
                water.water_health_score,
                water.water_health_status,
                water.observed_at AS water_health_observed_at,
                water.source_metadata AS water_health_source_metadata,
                aqi.aqi,
                aqi.pm25,
                aqi.pm10,
                aqi.no2,
                aqi.aqi_source_type,
                aqi.aqi_nearest_station_distance_m,
                aqi.temperature,
                aqi.humidity,
                aqi.observed_at AS aqi_observed_at,
                aqi.source_metadata AS aqi_source_metadata,
                GREATEST(aqi.observed_at, ndvi.observed_at, lst.observed_at, water.observed_at) AS date
            FROM zones z
            LEFT JOIN latest_aqi aqi ON aqi.zone_id = z.id
            LEFT JOIN latest_ndvi ndvi ON ndvi.zone_id = z.id
            LEFT JOIN latest_lst lst ON lst.zone_id = z.id
            LEFT JOIN latest_water water ON water.zone_id = z.id
            ORDER BY z.name
            """
        )
        rows = db.execute(stmt).mappings().all()
        out = []
        for r in rows:
            d = dict(r)
            d["source_metadata"] = {
                "aqi": d.pop("aqi_source_metadata"),
                "ndvi": d.pop("ndvi_source_metadata"),
                "lst": d.pop("lst_source_metadata"),
                "water_health": d.pop("water_health_source_metadata"),
            }
            d["geometry"] = json.loads(d.pop("geometry_geojson")) if d.get("geometry_geojson") else None
            d["composite"] = calculate_composite(
                aqi=d.get("aqi"),
                ndvi=d.get("ndvi"),
                lst=d.get("lst"),
                water_health_score=d.get("water_health_score"),
            )
            out.append(d)
        return out


@router.get("/municipalities/latest")
async def get_municipalities_latest(db_cm=Depends(get_db)):
    """Return aggregated metrics for real MMR municipality polygons."""
    try:
        with db_cm as db:
            return get_municipality_metrics(db)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Municipality aggregation failed: {exc}") from exc


@router.get("/water-bodies/latest")
async def get_water_bodies(db_cm=Depends(get_db)):
    """Return actual OSM water body polygons with water health scores."""
    try:
        with db_cm as db:
            return get_water_bodies_with_health(db)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Water bodies fetch failed: {exc}") from exc


@router.get("/surfaces/aqi/latest")
async def get_latest_aqi_surface():
    """Return metadata for the latest static, interpolated AQI image surface."""
    try:
        surface = load_latest_aqi_surface()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"AQI surface manifest unavailable: {exc}") from exc
    if surface is None:
        raise HTTPException(status_code=404, detail="No generated AQI surface is available")
    filename = surface.get("png_filename")
    if not isinstance(filename, str) or not filename or ".." in filename.replace("\\", "/").split("/"):
        raise HTTPException(status_code=503, detail="AQI surface manifest contains an unsafe PNG path")
    return {
        "metric": surface["metric"],
        "image_url": f"/surface-assets/{filename}",
        "coordinates": surface["mapbox_coordinates"],
        "generated_at": surface["generated_at"],
        "source_timestamp": surface["source_timestamp"],
        "methodology": surface["methodology"],
        "interpretation": surface["interpretation"],
        "nodata": True,
        "nodata_semantics": surface["nodata_semantics"],
        "station_count": surface["station_count"],
        "idw": surface["idw"],
    }


@router.get("/surfaces/ndvi/latest")
async def get_latest_ndvi_surface():
    """Return metadata for the latest real Sentinel-2 NDVI image surface."""
    # ═══════════════════════════════════════════════════════════════════════════
    # NDVI API DIAGNOSTICS
    # ═══════════════════════════════════════════════════════════════════════════
    print("[NDVI API ENTER] /api/surfaces/ndvi/latest endpoint called")
    import sys
    sys.stdout.flush()
    # ═══════════════════════════════════════════════════════════════════════════
    
    try:
        print("[NDVI API] About to call load_latest_ndvi_surface()")
        sys.stdout.flush()
        surface = load_latest_ndvi_surface()
        print(f"[NDVI API] load_latest_ndvi_surface returned: {surface is not None}")
        sys.stdout.flush()
    except Exception as exc:
        print(f"[NDVI API ERROR] Exception in load_latest_ndvi_surface: {exc}")
        sys.stdout.flush()
        raise HTTPException(status_code=503, detail=f"NDVI surface manifest unavailable: {exc}") from exc
    if surface is None:
        print("[NDVI API] Surface is None, returning 404")
        sys.stdout.flush()
        raise HTTPException(status_code=404, detail="No generated NDVI surface is available")
    
    print("[NDVI API] Building response object")
    sys.stdout.flush()
    filename = surface.get("png_filename")
    if not isinstance(filename, str) or not filename or ".." in filename.replace("\\", "/").split("/"):
        raise HTTPException(status_code=503, detail="NDVI surface manifest contains an unsafe PNG path")
    
    response = {
        "metric": surface["metric"], "image_url": f"/surface-assets/{filename}",
        "coordinates": surface["mapbox_coordinates"], "generated_at": surface["generated_at"],
        "source_timestamp": surface["source_timestamp"], "source_period": surface["source_period"],
        "source": surface["source"], "dataset": surface["dataset"],
        "methodology": surface["methodology"], "interpretation": surface["interpretation"],
        "preprocessing": surface["preprocessing"], "source_scale_m": surface["source_scale_m"],
        "nodata": True, "nodata_semantics": surface["nodata_semantics"],
    }
    print("[NDVI API RETURN] Returning response")
    sys.stdout.flush()
    return response


@router.get("/surfaces/lst/latest")
async def get_latest_lst_surface():
    """Return the latest generated LST surface metadata + asset URLs."""
    surface = load_latest_lst_surface()
    if surface is None:
        raise HTTPException(status_code=404, detail="No generated LST surface is available")

    # Validate filenames to prevent path traversal
    png_filename = surface["files"]["png"]
    glow_filename = surface["files"]["glow_png"]
    for filename in (png_filename, glow_filename):
        if not isinstance(filename, str) or not filename or ".." in filename.replace("\\", "/").split("/"):
            raise HTTPException(status_code=503, detail="LST surface manifest contains an unsafe file path")

    response = {
        "metric": surface["metric"],
        "image_url": f"/surface-assets/lst/{png_filename}",
        "glow_url": f"/surface-assets/lst/{glow_filename}",
        "coordinates": surface["coordinates"],
        "generated_at": surface["generated_at"],
        "source_timestamp": surface["timestamp"],
        "source_period": surface["source_period"],
        "dataset": surface["dataset"],
        "methodology": surface["methodology"],
        "unit": surface["unit"],
        "source_scale_m": surface["scale_m"],
        "lst_min_c": surface["lst_min_c"],
        "lst_max_c": surface["lst_max_c"],
        "lst_mean_c": surface["lst_mean_c"],
        "lst_median_c": surface["lst_median_c"],
        "glow_threshold_c": surface["glow_threshold_c"],
        "nodata": True,
        "nodata_semantics": "transparent",
        "valid_pixels": surface["valid_pixels"],
    }
    return response


@router.get("/zones/boundary")
async def get_zone_boundary(db_cm=Depends(get_db)):
    """Return real Mumbai administrative polygons for map-side filtering."""
    try:
        return _mumbai_boundary()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Mumbai boundary unavailable: {exc}") from exc


@lru_cache(maxsize=1)
def _mumbai_boundary() -> dict:
    features = []
    for query in (
        "Mumbai City District, Maharashtra, India",
        "Mumbai Suburban District, Maharashtra, India",
    ):
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "geojson", "polygon_geojson": 1, "limit": 1},
            headers={"User-Agent": "GeoSense/1.0"},
            timeout=20,
        )
        response.raise_for_status()
        result = response.json().get("features", [])
        if not result or result[0].get("geometry", {}).get("type") not in {"Polygon", "MultiPolygon"}:
            raise ValueError(f"No polygon returned for {query}")
        features.append(result[0])
    geometry = unary_union([shape(feature["geometry"]) for feature in features])
    return {"type": "Feature", "geometry": mapping(geometry)}


@router.get("/metrics/{locality_id}")
async def get_locality_metrics(locality_id: int, days: int = 14, db_cm=Depends(get_db)):
    # Interpret locality_id as zone_id in the new schema
    cutoff = datetime.utcnow() - timedelta(days=days)
    with db_cm as db:
        stmt = (
            select(
                EnvironmentData.observed_at.label("date"),
                EnvironmentData.ndvi,
                EnvironmentData.lst,
                EnvironmentData.ndwi,
                EnvironmentData.mndwi,
                EnvironmentData.ndci,
                EnvironmentData.turbidity_proxy,
                EnvironmentData.water_extent_m2,
                EnvironmentData.water_health_score,
                EnvironmentData.water_health_status,
                EnvironmentData.aqi,
                EnvironmentData.pm25,
                EnvironmentData.pm10,
                EnvironmentData.no2,
                EnvironmentData.temperature,
                EnvironmentData.humidity,
            )
            .where(EnvironmentData.zone_id == locality_id)
            .where(EnvironmentData.observed_at >= cutoff)
            .order_by(EnvironmentData.observed_at.desc())
        )
        rows = db.execute(stmt).mappings().all()
        out = []
        for r in rows:
            d = dict(r)
            out.append(d)
        return out


@router.get("/aqi/stations")
async def get_aqi_stations(db_cm=Depends(get_db)):
    with db_cm as db:
        # For each zone, get latest environment_data where aqi is not null
        subq = select(func.max(EnvironmentData.observed_at)).scalar_subquery()
        # Simpler: get latest per zone by ordering and distinct on zone
        stmt = (
            select(
                Zone.name.label("locality_name"),
                Zone.ward.label("ward"),
                EnvironmentData.aqi,
                EnvironmentData.pm25,
                EnvironmentData.pm10,
                EnvironmentData.no2,
                EnvironmentData.observed_at.label("timestamp"),
                EnvironmentData.aqi_source_type,
                EnvironmentData.aqi_nearest_station_distance_m,
            )
            .join(EnvironmentData, Zone.id == EnvironmentData.zone_id)
            .where(EnvironmentData.aqi != None)
            .order_by(Zone.name, EnvironmentData.observed_at.desc())
        )
        rows = db.execute(stmt).mappings().all()
        # keep the most recent per zone
        seen = set()
        out = []
        for r in rows:
            zname = r["locality_name"]
            if zname in seen:
                continue
            seen.add(zname)
            out.append(dict(r))
        return out


@router.get("/anomalies")
async def get_anomalies(days: int = 7, limit: int = 20, db_cm=Depends(get_db)):
    with db_cm as db:
        cutoff = datetime.utcnow() - timedelta(days=days)
        stmt = (
            select(
                AnomalyResult.id,
                AnomalyResult.zone_id.label("locality_id"),
                Zone.name.label("locality_name"),
                AnomalyResult.anomaly_score,
                AnomalyResult.root_cause,
                AnomalyResult.mitigation_suggestion.label("mitigation"),
                AnomalyResult.detected_at,
                AnomalyResult.observed_at,
                AnomalyResult.is_anomaly,
                AnomalyResult.evidence,
            )
            .join(Zone, AnomalyResult.zone_id == Zone.id)
            .where(AnomalyResult.detected_at >= cutoff)
            .where(AnomalyResult.is_anomaly.is_(True))
            .order_by(AnomalyResult.anomaly_score.desc())
            .limit(limit)
        )
        rows = db.execute(stmt).mappings().all()
        out = []
        for row in rows:
            item = dict(row)
            evidence = item.get("evidence") or {}
            raw_values = evidence.get("raw_values") or {}
            # The anomaly's relational anchor is usually the satellite row.  Use
            # stored structured evidence for all source-aligned raw values so AQI
            # and its provenance are not lost when their timestamps differ.
            item.update(
                {
                    "aqi": raw_values.get("aqi"),
                    "lst": raw_values.get("lst"),
                    "ndvi": raw_values.get("ndvi"),
                    "ndwi": raw_values.get("ndwi"),
                    "pm25": raw_values.get("pm25"),
                    "pm10": raw_values.get("pm10"),
                    "no2": raw_values.get("no2"),
                    "aqi_provenance": evidence.get("aqi_provenance"),
                    "evidence": evidence,
                }
            )
            out.append(item)
        return out


@router.post("/anomalies/detect")
async def trigger_anomaly_detection(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_anomaly_detection)
    return {
        "status": "detection_started",
        "message": "Anomaly detection running in background",
    }


def run_anomaly_detection():
    """Compatibility hook for the existing API trigger; work stays idempotent."""
    run_feature_anomaly_pipeline()


class FeedbackRequest(BaseModel):
    anomaly_id: int
    rating: bool
    actual_cause: Optional[str] = None


@router.post("/feedback")
async def submit_feedback(feedback: FeedbackRequest):
    # Feedback table is not part of the current schema/migrations.
    raise HTTPException(status_code=501, detail="Feedback endpoint not supported in current schema")


@router.get("/zones/{zone_id}/explanation")
async def get_zone_explanation(zone_id: int, db_cm=Depends(get_db)):
    """Return a structured, evidence-grounded explanation for a zone.

    The endpoint retrieves the latest Isolation Forest result for the zone,
    assembles a validated evidence object, and optionally uses an LLM to generate
    a rich natural language explanation based on the evidence and RAG knowledge.

    HTTP 404 — zone does not exist, or no Isolation Forest result exists yet.
    HTTP 503 — database error during evidence assembly.
    """
    try:
        with db_cm as db:
            result = await build_full_explanation(db, zone_id)
            return result
    except ZoneNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NoAnomalyResultError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Evidence assembly failed: {exc}") from exc


@router.get("/health")
async def health_check():
    return {"status": "healthy", "phase": "2", "version": "2.0.0"}


@router.get("/system/status")
async def get_system_status(db_cm=Depends(get_db)):
    """Read-only operational evidence for scheduled-history accumulation."""
    with db_cm as db:
        return get_operational_status(db)
