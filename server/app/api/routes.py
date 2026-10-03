from typing import Optional
import json
from functools import lru_cache
import requests
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

from sqlalchemy import text, select, func
import rasterio
import numpy as np
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
from app.services.surfaces.water_health_surface import load_latest_water_health_surface
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


def _safe_surface_asset(surface: dict, key: str) -> str | None:
    filename = surface.get(key)
    if not isinstance(filename, str) or not filename or ".." in filename.replace("\\", "/").split("/"):
        return None
    return filename


def _versioned_water_health_asset(surface: dict, filename: str, checksum_key: str) -> str:
    """Give overwritten Water Health PNG paths a content-versioned URL."""
    checksum = (surface.get("checksums") or {}).get(checksum_key)
    if not isinstance(checksum, str) or not checksum:
        checksum = str(surface.get("generated_at") or "current")
    return f"/surface-assets/{filename}?v={checksum}"


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

    sharp_rel = _safe_surface_asset(surface, "sharp_png_filename") or _safe_surface_asset(surface, "png_filename")
    glow_rel  = _safe_surface_asset(surface, "glow_png_filename")
    halo_rel  = _safe_surface_asset(surface, "halo_png_filename")
    if not sharp_rel:
        raise HTTPException(status_code=503, detail="NDVI surface manifest contains an unsafe PNG path")

    response = {
        "metric": surface["metric"],
        "image_url": f"/surface-assets/{sharp_rel}",
        "sharp_url": f"/surface-assets/{sharp_rel}",
        "glow_url":  f"/surface-assets/{glow_rel}"  if glow_rel  else None,
        "halo_url":  f"/surface-assets/{halo_rel}"  if halo_rel  else None,
        "coordinates": surface["mapbox_coordinates"], "generated_at": surface["generated_at"],
        "source_timestamp": surface["source_timestamp"], "source_period": surface["source_period"],
        "source": surface["source"], "dataset": surface["dataset"],
        "methodology": surface["methodology"], "interpretation": surface["interpretation"],
        "semantic_label": surface.get("semantic_label"),
        "visualization": surface.get("visualization"),
        "preprocessing": surface["preprocessing"], "source_scale_m": surface["source_scale_m"],
        "nodata": True, "nodata_semantics": surface["nodata_semantics"],
        "valid_pixels": surface.get("valid_pixels"),
        "ndvi_statistics": surface.get("ndvi_statistics"),
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

    checksums = surface.get("checksums") or {}
    png_version = checksums.get("png_sha256")
    glow_version = checksums.get("glow_png_sha256")
    png_url = f"/surface-assets/lst/{png_filename}"
    glow_url = f"/surface-assets/lst/{glow_filename}"
    if isinstance(png_version, str) and png_version:
        png_url = f"{png_url}?v={png_version}"
    if isinstance(glow_version, str) and glow_version:
        glow_url = f"{glow_url}?v={glow_version}"

    response = {
        "metric": surface["metric"],
        "image_url": png_url,
        "glow_url": glow_url,
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
        "visualization": surface.get("visualization"),
        "nodata": True,
        "nodata_semantics": "transparent",
        "valid_pixels": surface["valid_pixels"],
    }
    return response


@router.get("/surfaces/water-health/latest")
async def get_latest_water_health_surface():
    """Return metadata for the latest real Sentinel-2 Water Health image surface."""
    try:
        surface = load_latest_water_health_surface()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Water Health surface manifest unavailable: {exc}") from exc
    if surface is None:
        raise HTTPException(status_code=404, detail="No generated Water Health surface is available")

    sharp_rel = _safe_surface_asset(surface, "sharp_png_filename") or _safe_surface_asset(surface, "png_filename")
    glow_rel  = _safe_surface_asset(surface, "glow_png_filename")
    halo_rel  = _safe_surface_asset(surface, "halo_png_filename")
    if not sharp_rel:
        raise HTTPException(status_code=503, detail="Water Health surface manifest contains an unsafe PNG path")

    checksums = surface.get("checksums") or {}
    sharp_url = _versioned_water_health_asset(
        surface,
        sharp_rel,
        "sharp_png_sha256" if checksums.get("sharp_png_sha256") else "png_sha256",
    )
    glow_url = _versioned_water_health_asset(surface, glow_rel, "glow_png_sha256") if glow_rel else None
    halo_url = _versioned_water_health_asset(surface, halo_rel, "halo_png_sha256") if halo_rel else None

    response = {
        "metric": surface["metric"],
        "image_url": sharp_url,
        "sharp_url": sharp_url,
        "glow_url": glow_url,
        "halo_url": halo_url,
        "coordinates": surface["mapbox_coordinates"],
        "generated_at": surface["generated_at"],
        "source_timestamp": surface.get("source_timestamp"),
        "source_period": surface.get("source_period"),
        "source": surface.get("source"),
        "dataset": surface.get("dataset"),
        "methodology": surface["methodology"],
        "interpretation": surface["interpretation"],
        "semantic_label": surface.get("semantic_label"),
        "visualization": surface.get("visualization"),
        "display_percentiles": surface.get("display_percentiles"),
        "preprocessing": surface.get("preprocessing"),
        "source_scale_m": surface["source_scale_m"],
        "scale_m": surface.get("scale_m"),
        "unit": surface.get("unit"),
        "wh_min": surface.get("wh_min"),
        "wh_max": surface.get("wh_max"),
        "wh_mean": surface.get("wh_mean"),
        "wh_median": surface.get("wh_median"),
        "water_health_statistics": surface.get("water_health_statistics"),
        "valid_pixels": surface.get("valid_pixels"),
        "nodata": True,
        "nodata_semantics": surface["nodata_semantics"],
    }
    return response


@router.get("/surfaces/lst/value")
async def get_lst_pixel_value(lon: float, lat: float):
    """Return pixel-level LST value from the underlying GeoTIFF."""
    surface = load_latest_lst_surface()
    if not surface:
        raise HTTPException(status_code=404, detail="No LST surface available")
        
    tif_filename = surface["files"]["geotiff"]
    from pathlib import Path
    import os
    import numpy as np
    import rasterio
    
    SERVER_ROOT = Path(__file__).resolve().parents[2]
    tif_path = SERVER_ROOT / "data" / "surfaces" / "lst" / tif_filename
    
    if not tif_path.exists():
        raise HTTPException(status_code=404, detail="GeoTIFF not found")
        
    try:
        with rasterio.open(tif_path) as dataset:
            if not (dataset.bounds.left <= lon <= dataset.bounds.right and dataset.bounds.bottom <= lat <= dataset.bounds.top):
                return {
                    "metric": "lst", "longitude": lon, "latitude": lat,
                    "value_c": None, "nodata": True, "source": surface["methodology"],
                    "resolution_m": surface["scale_m"], "source_period": surface["source_period"]
                }
            
            row, col = dataset.index(lon, lat)
            from rasterio.windows import Window
            val = dataset.read(1, window=Window(col, row, 1, 1))[0, 0]
            is_nodata = bool(val == dataset.nodata or not np.isfinite(val))
            
            return {
                "metric": "lst",
                "longitude": lon,
                "latitude": lat,
                "value_c": None if is_nodata else round(float(val), 2),
                "nodata": is_nodata,
                "source": "Landsat 8/9 Collection 2 Level-2 Surface Temperature",
                "resolution_m": surface["scale_m"],
                "source_period": surface["source_period"]
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/surfaces/ndvi/value")
async def get_ndvi_pixel_value(lon: float, lat: float):
    """Return pixel-level NDVI value from the underlying GeoTIFF."""
    surface = load_latest_ndvi_surface()
    if not surface:
        raise HTTPException(status_code=404, detail="No NDVI surface available")
        
    tif_filename = surface.get("geotiff_filename")
    if not tif_filename:
        raise HTTPException(status_code=404, detail="NDVI GeoTIFF not found in manifest")
        
    from pathlib import Path
    import os
    import numpy as np
    import rasterio
    
    SERVER_ROOT = Path(__file__).resolve().parents[2]
    # In NDVI, the filename is usually relative to output_root e.g. "ndvi/ndvi_2026...tif"
    # But let's check if it already has 'ndvi/' prefix.
    # We'll just join it to data/surfaces.
    tif_path = SERVER_ROOT / "data" / "surfaces" / tif_filename
    
    if not tif_path.exists():
        # Fallback if it just gives basename
        tif_path = SERVER_ROOT / "data" / "surfaces" / "ndvi" / os.path.basename(tif_filename)
        if not tif_path.exists():
            raise HTTPException(status_code=404, detail="GeoTIFF not found on disk")
        
    try:
        with rasterio.open(tif_path) as dataset:
            if not (dataset.bounds.left <= lon <= dataset.bounds.right and dataset.bounds.bottom <= lat <= dataset.bounds.top):
                return {
                    "metric": "ndvi", "longitude": lon, "latitude": lat,
                    "value": None, "nodata": True, "source": surface.get("methodology"),
                    "resolution_m": surface.get("source_scale_m"), "source_period": surface.get("source_period")
                }
            
            row, col = dataset.index(lon, lat)
            from rasterio.windows import Window
            val = dataset.read(1, window=Window(col, row, 1, 1))[0, 0]
            is_nodata = bool(val == dataset.nodata or not np.isfinite(val))
            
            return {
                "metric": "ndvi",
                "longitude": lon,
                "latitude": lat,
                "value": None if is_nodata else round(float(val), 3),
                "nodata": is_nodata,
                "source": "Sentinel-2 NDVI",
                "resolution_m": surface.get("source_scale_m"),
                "source_period": surface.get("source_period")
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/surfaces/water-health/value")
async def get_water_health_pixel_value(lon: float, lat: float):
    """Return pixel-level Water Health value from the underlying scientific GeoTIFF."""
    surface = load_latest_water_health_surface()
    if not surface:
        raise HTTPException(status_code=404, detail="No Water Health surface available")

    tif_filename = surface.get("geotiff_filename")
    if not tif_filename:
        raise HTTPException(status_code=404, detail="Water Health GeoTIFF not found in manifest")

    from pathlib import Path as _WhPath
    import os as _WhOs
    import numpy as _WhNp
    import rasterio as _WhRasterio

    _SERVER_ROOT = _WhPath(__file__).resolve().parents[2]
    tif_path = _SERVER_ROOT / "data" / "surfaces" / tif_filename
    if not tif_path.exists():
        tif_path = _SERVER_ROOT / "data" / "surfaces" / "water-health" / _WhOs.path.basename(tif_filename)
        if not tif_path.exists():
            raise HTTPException(status_code=404, detail="GeoTIFF not found on disk")

    try:
        with _WhRasterio.open(tif_path) as dataset:
            if not (dataset.bounds.left <= lon <= dataset.bounds.right and dataset.bounds.bottom <= lat <= dataset.bounds.top):
                return {
                    "metric": "water_health",
                    "longitude": lon,
                    "latitude": lat,
                    "value": None,
                    "nodata": True,
                    "source": surface.get("methodology"),
                    "resolution_m": surface.get("source_scale_m"),
                    "source_period": surface.get("source_period"),
                }
            row, col = dataset.index(lon, lat)
            from rasterio.windows import Window as _WhWindow
            val = dataset.read(1, window=_WhWindow(col, row, 1, 1))[0, 0]
            is_nodata = bool(val == dataset.nodata or not _WhNp.isfinite(val))
            return {
                "metric": "water_health",
                "longitude": lon,
                "latitude": lat,
                "value": None if is_nodata else round(float(val), 3),
                "nodata": is_nodata,
                "source": "Sentinel-2 derived Water Health raster",
                "resolution_m": surface.get("source_scale_m"),
                "source_period": surface.get("source_period"),
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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


@router.get("/analysis/point")
async def get_point_analysis(lon: float, lat: float, db_cm=Depends(get_db)):
    """Return 3-level analysis for a coordinate: Pixel, Cell (300m), Municipality.

    Hierarchy:
      1. PIXEL        — exact raster values from scientific GeoTIFFs (windowed reads)
      2. DENSE CELL   — 300m analytical grid: aggregated metrics, anomalies, history
      3. MUNICIPALITY — administrative boundary containment (Mumbai / Thane / Mira-Bhayandar)

    These three levels are intentionally distinct: PIXEL ≠ CELL ≠ MUNICIPALITY.
    """
    from app.services.municipality_boundaries import load_municipality_boundaries, MunicipalityBoundaryError
    from shapely.geometry import Point as ShapelyPoint

    # ══════════════════════════════════════════════════════════════════════
    # 1. PIXEL LEVEL — exact scientific raster pixel reads (windowed, 1x1)
    # ══════════════════════════════════════════════════════════════════════
    pixel_ndvi = None
    try:
        ndvi_res = await get_ndvi_pixel_value(lon, lat)
        if ndvi_res:
            pixel_ndvi = {
                "value": ndvi_res.get("value"),
                "nodata": bool(ndvi_res.get("nodata", True)),
                "source": ndvi_res.get("source"),
                "resolution_m": ndvi_res.get("resolution_m"),
                "source_period": ndvi_res.get("source_period"),
            }
    except HTTPException:
        pass
    except Exception:
        pass

    pixel_lst = None
    try:
        lst_res = await get_lst_pixel_value(lon, lat)
        if lst_res:
            pixel_lst = {
                "value_c": lst_res.get("value_c"),
                "nodata": bool(lst_res.get("nodata", True)),
                "source": lst_res.get("source"),
                "resolution_m": lst_res.get("resolution_m"),
                "source_period": lst_res.get("source_period"),
            }
    except HTTPException:
        pass
    except Exception:
        pass

    pixel_aqi = None
    try:
        aqi_surface = load_latest_aqi_surface()
        if aqi_surface:
            from pathlib import Path as _Path
            import rasterio as _rasterio
            from rasterio.windows import Window as _Window
            _SERVER_ROOT = _Path(__file__).resolve().parents[2]
            _manifest_path = _SERVER_ROOT / "data" / "surfaces" / "manifest.json"
            if _manifest_path.exists():
                import json as _json
                _manifest = _json.loads(_manifest_path.read_text(encoding="utf-8"))
                _aqi_rec = _manifest.get("surfaces", {}).get("aqi")
                if _aqi_rec and _aqi_rec.get("geotiff_filename"):
                    _tif_path = _SERVER_ROOT / "data" / "surfaces" / _aqi_rec["geotiff_filename"]
                    if _tif_path.exists():
                        with _rasterio.open(_tif_path) as _ds:
                            _in_bounds = (_ds.bounds.left <= lon <= _ds.bounds.right and
                                          _ds.bounds.bottom <= lat <= _ds.bounds.top)
                            if _in_bounds:
                                _row, _col = _ds.index(lon, lat)
                                _val = _ds.read(1, window=_Window(_col, _row, 1, 1))[0, 0]
                                _is_nodata = bool(_val == _ds.nodata or not np.isfinite(_val))
                                pixel_aqi = {
                                    "value": None if _is_nodata else int(round(float(_val))),
                                    "nodata": _is_nodata,
                                    "source": aqi_surface.get("methodology"),
                                    "resolution_m": None,
                                    "note": "IDW interpolation from CPCB monitoring stations",
                                }
    except Exception:
        pass

    pixel_water_health = None
    try:
        wh_res = await get_water_health_pixel_value(lon, lat)
        if wh_res:
            pixel_water_health = {
                "value": wh_res.get("value"),
                "nodata": bool(wh_res.get("nodata", True)),
                "source": wh_res.get("source"),
                "resolution_m": wh_res.get("resolution_m"),
                "source_period": wh_res.get("source_period"),
            }
    except HTTPException:
        pass
    except Exception:
        pass

    pixel_block = {
        "longitude": lon,
        "latitude": lat,
        "ndvi": pixel_ndvi,
        "lst": pixel_lst,
        "aqi": pixel_aqi,
        "water_health": pixel_water_health,
    }

    # ══════════════════════════════════════════════════════════════════════
    # 2. DENSE ANALYTICAL CELL — 300m grid (spatial_cells table)
    # ══════════════════════════════════════════════════════════════════════
    cell_block = None
    with db_cm as db:
        cell_stmt = text("""
            WITH point AS (
                SELECT ST_GeomFromEWKT('SRID=4326;POINT(' || :lon || ' ' || :lat || ')') AS geom
            ),
            matched_cell AS (
                -- 1st priority: exact containment
                SELECT sc.id, sc.cell_code, sc.resolution_m, sc.municipality_name,
                       ST_X(sc.centroid) AS centroid_lon,
                       ST_Y(sc.centroid) AS centroid_lat,
                       ST_Distance(sc.centroid::geography, point.geom::geography) AS dist_m,
                       1 AS match_rank
                FROM spatial_cells sc, point
                WHERE ST_Contains(sc.geometry, point.geom)
                LIMIT 1
            ),
            fallback_cell AS (
                -- 2nd priority: nearest cell within 1 km (for clicks on gaps / edges)
                SELECT sc.id, sc.cell_code, sc.resolution_m, sc.municipality_name,
                       ST_X(sc.centroid) AS centroid_lon,
                       ST_Y(sc.centroid) AS centroid_lat,
                       ST_Distance(sc.centroid::geography, point.geom::geography) AS dist_m,
                       2 AS match_rank
                FROM spatial_cells sc, point
                WHERE NOT EXISTS (SELECT 1 FROM matched_cell)
                  AND ST_DWithin(sc.centroid::geography, point.geom::geography, 1000)
                ORDER BY sc.centroid <-> point.geom
                LIMIT 1
            ),
            chosen AS (
                SELECT * FROM matched_cell UNION ALL SELECT * FROM fallback_cell LIMIT 1
            )
            SELECT c.*,
                   ed.aqi AS ed_aqi, ed.ndvi AS ed_ndvi, ed.lst AS ed_lst,
                   ed.water_health_score AS ed_water_health, ed.observed_at AS ed_observed_at,
                   ar.is_anomaly AS ar_is_anomaly, ar.anomaly_score AS ar_score,
                   ar.anomaly_type AS ar_type, ar.root_cause AS ar_root_cause,
                   ar.evidence AS ar_evidence, ar.detected_at AS ar_detected_at
            FROM chosen c
            LEFT JOIN (
                SELECT DISTINCT ON (cell_id) *
                FROM environment_data
                WHERE cell_id IS NOT NULL
                ORDER BY cell_id, observed_at DESC, id DESC
            ) ed ON ed.cell_id = c.id
            LEFT JOIN (
                SELECT DISTINCT ON (cell_id) *
                FROM anomaly_results
                WHERE cell_id IS NOT NULL
                ORDER BY cell_id, detected_at DESC, id DESC
            ) ar ON ar.cell_id = c.id
        """)
        cell_row = db.execute(cell_stmt, {"lon": lon, "lat": lat}).mappings().one_or_none()

        if cell_row:
            anomaly_block = None
            if cell_row["ar_is_anomaly"] is not None:
                anomaly_block = {
                    "flag": bool(cell_row["ar_is_anomaly"]),
                    "score": cell_row["ar_score"],
                    "anomaly_type": cell_row["ar_type"],
                    "root_cause": cell_row["ar_root_cause"],
                    "detected_at": cell_row["ar_detected_at"].isoformat() if cell_row["ar_detected_at"] else None,
                }
            cell_block = {
                "id": cell_row["id"],
                "cell_code": cell_row["cell_code"],
                "resolution_m": cell_row["resolution_m"],
                "match_type": "contains" if cell_row["match_rank"] == 1 else "nearest",
                "distance_to_centroid_m": round(cell_row["dist_m"], 1),
                "centroid": {
                    "longitude": cell_row["centroid_lon"],
                    "latitude": cell_row["centroid_lat"],
                },
                "metrics": {
                    "aqi": cell_row["ed_aqi"],
                    "ndvi": cell_row["ed_ndvi"],
                    "lst": cell_row["ed_lst"],
                    "water_health_score": cell_row["ed_water_health"],
                    "observed_at": cell_row["ed_observed_at"].isoformat() if cell_row["ed_observed_at"] else None,
                },
                "anomaly": anomaly_block,
                "municipality_name_from_cell": cell_row["municipality_name"],
            }

    # ══════════════════════════════════════════════════════════════════════
    # 3. MUNICIPALITY — administrative containment (local GeoJSON boundaries)
    # ══════════════════════════════════════════════════════════════════════
    municipality_block = None
    try:
        boundaries = load_municipality_boundaries()
        click_point = ShapelyPoint(lon, lat)
        for b in boundaries:
            if b["shapely_geom"].contains(click_point):
                municipality_block = {
                    "id": b["id"],
                    "name": b["name"],
                    "source": "local GeoJSON boundary containment",
                }
                break
    except (MunicipalityBoundaryError, Exception):
        pass

    if municipality_block is None and cell_block is not None and cell_block["municipality_name_from_cell"]:
        municipality_block = {
            "id": None,
            "name": cell_block["municipality_name_from_cell"],
            "source": "spatial_cells.municipality_name fallback",
        }

    return {
        "location": {
            "longitude": lon,
            "latitude": lat,
        },
        "pixel": pixel_block,
        "cell": cell_block,
        "municipality": municipality_block,
    }


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
async def get_zone_explanation(zone_id: int, pixel_lst: Optional[float] = None, db_cm=Depends(get_db)):
    """Return a structured, evidence-grounded explanation for a zone.

    The endpoint retrieves the latest Isolation Forest result for the zone,
    assembles a validated evidence object, and optionally uses an LLM to generate
    a rich natural language explanation based on the evidence and RAG knowledge.

    HTTP 404 — zone does not exist, or no Isolation Forest result exists yet.
    HTTP 503 — database error during evidence assembly.
    """
    try:
        with db_cm as db:
            result = await build_full_explanation(db, zone_id, pixel_lst)
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
