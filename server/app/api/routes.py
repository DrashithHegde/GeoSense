"""GeoSense map API. Every endpoint works on the city of the request (see app/main.py:
?city=<id>, or the city that contains ?lon=&lat=).

Three levels are kept apart everywhere: PIXEL (exact GeoTIFF value) ≠ CELL (300 m analytical
cell) ≠ MUNICIPALITY (administrative boundary).
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import rasterio
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from rasterio.windows import Window
from shapely.geometry import mapping
from sqlalchemy import text

from app.core.cities import CITIES, available_cities, city_path, get_city
from app.database import get_db
from app.services.surfaces.lst_surface import load_latest_lst_surface
from app.services.surfaces.ndvi_surface import load_latest_ndvi_surface
from app.services.surfaces.water_health_surface import load_latest_water_health_surface

logger = logging.getLogger(__name__)
router = APIRouter()

SURFACES = city_path("surfaces")
MANIFEST = city_path("surfaces", "manifest.json")


def _db_cm():
    """Return the session context manager itself (used as `with db_cm as db`)."""
    return get_db()


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────

def _manifest_surfaces() -> dict[str, Any]:
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8")).get("surfaces", {}) or {}
    except FileNotFoundError:
        return {}


def _safe_rel(value: Any) -> str | None:
    """A manifest file path that stays inside the city's surfaces folder."""
    if not isinstance(value, str) or not value:
        return None
    parts = value.replace("\\", "/").split("/")
    if ".." in parts or value.startswith("/"):
        return None
    return "/".join(parts)


def asset_url(rel: str | None, version: Any = None) -> str | None:
    """URL of a map file of the current city (served by the /surface-assets/<city> mount)."""
    rel = _safe_rel(rel)
    if rel is None:
        return None
    v = f"?v={version}" if isinstance(version, str) and version else ""
    return f"/surface-assets/{get_city().id}/{rel}{v}"


def _layer_urls(surface: dict, folder: str | None = None) -> dict[str, str | None]:
    """sharp/glow/halo image URLs of a manifest record, each stamped with its content hash."""
    ck = surface.get("checksums") or {}
    files = surface.get("files") or {}
    fallback = str(surface.get("generated_at") or "current")

    def rel(key_rel: str, key_file: str) -> str | None:
        if surface.get(key_rel):
            return surface[key_rel]
        if folder and files.get(key_file):
            return f"{folder}/{files[key_file]}"
        return None

    sharp = rel("sharp_png_filename", "sharp_png") or rel("png_filename", "png")
    out = {
        "sharp_url": asset_url(sharp, ck.get("sharp_png_sha256") or ck.get("png_sha256") or fallback),
        "glow_url": asset_url(rel("glow_png_filename", "glow_png"), ck.get("glow_png_sha256") or fallback),
        "halo_url": asset_url(rel("halo_png_filename", "halo_png"), ck.get("halo_png_sha256") or fallback),
    }
    out["image_url"] = out["sharp_url"]
    return out


def _tif_path(surface: dict | None, folder: str) -> Path | None:
    """Scientific GeoTIFF of a manifest record (the truth the map images are drawn from)."""
    if not surface:
        return None
    rel = _safe_rel(surface.get("geotiff_filename"))
    candidates = []
    if rel:
        candidates += [SURFACES / rel, SURFACES / folder / Path(rel).name]
    name = (surface.get("files") or {}).get("geotiff")
    if _safe_rel(name):
        candidates.append(SURFACES / folder / name)
    return next((p for p in candidates if p.exists()), None)


def _read_pixel(path: Path, lon: float, lat: float) -> tuple[float | None, bool]:
    """Exact 1x1 window read; (value, nodata)."""
    with rasterio.open(path) as ds:
        b = ds.bounds
        if not (b.left <= lon <= b.right and b.bottom <= lat <= b.top):
            return None, True
        r, c = ds.index(lon, lat)
        v = float(ds.read(1, window=Window(c, r, 1, 1))[0, 0])
        nodata = (ds.nodata is not None and v == ds.nodata) or not math.isfinite(v)
    return (None if nodata else v), nodata


# ─────────────────────────────────────────────────────────────────────────────
# cities and boundaries
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/cities")
async def list_cities():
    """Every city GeoSense covers, and which of its layers are ready."""
    ready = set(available_cities())
    out = []
    for cid, city in CITIES.items():
        manifest = city.data_dir / "surfaces" / "manifest.json"
        layers = {}
        if manifest.exists():
            try:
                s = json.loads(manifest.read_text(encoding="utf-8")).get("surfaces", {}) or {}
                layers = {k: (v or {}).get("generation_status", "generated")
                          for k, v in s.items() if k in ("ndvi", "lst", "water_health", "aqi", "composite")}
            except Exception:
                layers = {}
        out.append({**city.public(), "boundaries": cid in ready, "layers": layers,
                    "ready": cid in ready and any(v == "generated" for v in layers.values())})
    return {"cities": out}


@router.get("/zones/boundary")
@router.get("/boundary")
async def get_study_region_boundary():
    """The current city's study region (union of its municipalities)."""
    from app.services.municipality_boundaries import load_study_region_geometry
    try:
        return {"type": "Feature", "properties": {"city": get_city().id},
                "geometry": mapping(load_study_region_geometry())}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"{get_city().name} boundary unavailable: {exc}") from exc


@router.get("/municipalities/latest")
async def get_municipalities_latest(db_cm=Depends(_db_cm)):
    """The city's municipality polygons with mean cell values from the latest ML snapshot."""
    from app.services.municipality_aggregation import get_municipality_metrics
    try:
        with db_cm as db:
            return get_municipality_metrics(db)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Municipality aggregation failed: {exc}") from exc


# ─────────────────────────────────────────────────────────────────────────────
# map layers (latest surface of each layer)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/surfaces/aqi/latest")
async def get_latest_aqi_surface():
    """Station-based CPCB AQI surface (OpenAQ -> CPCB AQI -> IDW).

    Always 200 with `available`; when coverage is insufficient or the readings are older than
    48 h the response says so (with the station audit) instead of serving a proxy surface.
    """
    from app.services.surfaces import aqi_refresh
    from app.services.surfaces.aqi_station_surface import aqi_expired, reading_age

    surface = _manifest_surfaces().get("aqi") or {}
    expired = surface.get("generation_status") == "generated" and aqi_expired(surface)
    st = aqi_refresh.state()
    refreshing = bool(st["running"])
    base = {
        "metric": "aqi",
        "city": get_city().id,
        "available": False,
        "status": "expired" if expired else surface.get("generation_status", "not_generated"),
        "reason": (("AQI data expired (readings older than 48 hours) — refreshing now." if refreshing else
                    "Station readings are now older than 48 hours, so the AQI layer is hidden. Regenerate it: "
                    f"python scripts/generate_aqi_station_surface.py --city {get_city().id}")
                   if expired else surface.get("reason")),
        "reading_age_hours": reading_age(surface),
        "refresh": {"auto": aqi_refresh.enabled(), "running": refreshing,
                    "last_attempt": st["last_attempt"], "last_result": st["last_result"]},
        "methodology": surface.get("methodology"),
        "stations": surface.get("stations", []),
        "audit": surface.get("audit"),
        "generated_at": surface.get("generated_at"),
    }
    if surface.get("generation_status") != "generated" or expired:
        return base
    return {
        **base, **_layer_urls(surface, "aqi"),
        "available": True,
        "coordinates": surface["mapbox_coordinates"],
        "source_timestamp": surface.get("source_timestamp"),
        "interpretation": surface.get("interpretation"),
        "interpolation": surface.get("interpolation"),
        "visualization": surface.get("visualization"),
        "aqi_min": surface.get("aqi_min"), "aqi_max": surface.get("aqi_max"), "aqi_mean": surface.get("aqi_mean"),
        "nodata": True,
        "nodata_semantics": surface.get("nodata_semantics"),
    }


@router.get("/surfaces/ndvi/latest")
async def get_latest_ndvi_surface():
    """The latest real Sentinel-2 NDVI surface of the city."""
    try:
        surface = load_latest_ndvi_surface()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"NDVI surface manifest unavailable: {exc}") from exc
    if surface is None:
        raise HTTPException(status_code=404, detail=f"No NDVI surface has been generated for {get_city().name} yet")
    urls = _layer_urls(surface, "ndvi")
    if not urls["sharp_url"]:
        raise HTTPException(status_code=503, detail="NDVI surface manifest contains an unsafe image path")
    return {
        "metric": surface["metric"], "city": get_city().id, **urls,
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


@router.get("/surfaces/lst/latest")
async def get_latest_lst_surface():
    """The latest Landsat LST surface of the city."""
    surface = load_latest_lst_surface()
    if surface is None:
        raise HTTPException(status_code=404, detail=f"No LST surface has been generated for {get_city().name} yet")
    urls = _layer_urls(surface, "lst")
    if not urls["sharp_url"]:
        raise HTTPException(status_code=503, detail="LST surface manifest contains an unsafe file path")
    return {
        "metric": surface["metric"], "city": get_city().id, **urls,
        "coordinates": surface.get("mapbox_coordinates") or surface["coordinates"],
        "generated_at": surface["generated_at"],
        "source_timestamp": surface["timestamp"],
        "source_period": surface["source_period"],
        "dataset": surface["dataset"],
        "methodology": surface["methodology"],
        "unit": surface["unit"],
        "source_scale_m": surface["scale_m"],
        "lst_min_c": surface["lst_min_c"], "lst_max_c": surface["lst_max_c"],
        "lst_mean_c": surface["lst_mean_c"], "lst_median_c": surface["lst_median_c"],
        "glow_threshold_c": surface.get("glow_threshold_c"),
        "visualization": surface.get("visualization"),
        "nodata": True,
        "nodata_semantics": "transparent",
        "valid_pixels": surface["valid_pixels"],
    }


@router.get("/surfaces/water-health/latest")
async def get_latest_water_health_surface():
    """The latest real Sentinel-2 Water Health surface of the city."""
    try:
        surface = load_latest_water_health_surface()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Water Health surface manifest unavailable: {exc}") from exc
    if surface is None:
        raise HTTPException(status_code=404, detail=f"No Water Health surface has been generated for {get_city().name} yet")
    urls = _layer_urls(surface, "water-health")
    if not urls["sharp_url"]:
        raise HTTPException(status_code=503, detail="Water Health surface manifest contains an unsafe image path")
    return {
        "metric": surface["metric"], "city": get_city().id, **urls,
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
        "wh_min": surface.get("wh_min"), "wh_max": surface.get("wh_max"),
        "wh_mean": surface.get("wh_mean"), "wh_median": surface.get("wh_median"),
        "water_health_statistics": surface.get("water_health_statistics"),
        "valid_pixels": surface.get("valid_pixels"),
        "nodata": True,
        "nodata_semantics": surface["nodata_semantics"],
    }


@router.get("/surfaces/composite/latest")
async def get_latest_composite_surface():
    """The latest composite environmental stress surface of the city."""
    surfaces = _manifest_surfaces()
    surface = surfaces.get("composite")
    if not surface or surface.get("generation_status", "generated") != "generated":
        raise HTTPException(status_code=404, detail=f"No composite surface has been generated for {get_city().name} yet")
    urls = _layer_urls(surface, "composite")
    if not urls["sharp_url"]:
        raise HTTPException(status_code=503, detail="Composite surface manifest contains an unsafe image path")
    return {
        "metric": surface["metric"], "city": get_city().id, **urls,
        "coordinates": surface.get("mapbox_coordinates") or (surfaces.get("lst") or {}).get("mapbox_coordinates"),
        "generated_at": surface["generated_at"],
        "source_timestamp": surface.get("source_timestamp", surface["generated_at"]),
        "methodology": surface.get("methodology", "Composite environmental stress"),
        "interpretation": surface.get("interpretation", "Relative stress index 0-1"),
        "inputs_used": surface.get("inputs_used"),
        "weights": surface.get("weights"),
        "visualization": surface.get("visualization"),
        "nodata": True,
        "nodata_semantics": "transparent outside the city",
    }


# ─────────────────────────────────────────────────────────────────────────────
# exact pixel values
# ─────────────────────────────────────────────────────────────────────────────

def _pixel(metric: str, folder: str, lon: float, lat: float, digits: int, surface: dict | None,
           source: str, scale_key: str = "source_scale_m") -> dict | None:
    path = _tif_path(surface, folder)
    if path is None:
        return None
    v, nodata = _read_pixel(path, lon, lat)
    return {"metric": metric, "longitude": lon, "latitude": lat,
            "value": None if v is None else round(v, digits), "nodata": nodata, "source": source,
            "resolution_m": (surface or {}).get(scale_key), "source_period": (surface or {}).get("source_period")}


@router.get("/surfaces/lst/value")
async def get_lst_pixel_value(lon: float, lat: float):
    """Pixel-level LST from the scientific GeoTIFF."""
    out = _pixel("lst", "lst", lon, lat, 2, load_latest_lst_surface(),
                 "Landsat 8/9 Collection 2 Level-2 Surface Temperature", "scale_m")
    if out is None:
        raise HTTPException(status_code=404, detail="No LST GeoTIFF for this city")
    out["value_c"] = out.pop("value")
    return out


@router.get("/surfaces/ndvi/value")
async def get_ndvi_pixel_value(lon: float, lat: float):
    """Pixel-level NDVI from the scientific GeoTIFF."""
    out = _pixel("ndvi", "ndvi", lon, lat, 3, load_latest_ndvi_surface(), "Sentinel-2 NDVI")
    if out is None:
        raise HTTPException(status_code=404, detail="No NDVI GeoTIFF for this city")
    return out


@router.get("/surfaces/ndmi/latest")
async def get_latest_ndmi_surface():
    """Latest supporting Sentinel-2 vegetation-moisture index (not an independent map layer)."""
    surface = _manifest_surfaces().get("ndmi")
    if not surface or surface.get("generation_status") != "generated":
        raise HTTPException(status_code=404, detail=f"No NDMI index has been generated for {get_city().name} yet")
    rec = {
        "metric": "ndmi",
        "city": get_city().id,
        "generated_at": surface.get("generated_at"),
        "source_period": surface.get("source_period"),
        "source": surface.get("source"),
        "dataset": surface.get("dataset"),
        "methodology": surface.get("methodology"),
        "formula": surface.get("formula"),
        "interpretation": surface.get("interpretation"),
        "semantic_label": surface.get("semantic_label"),
        "scale_m": surface.get("scale_m"),
        "source_scale_m": surface.get("source_scale_m"),
        "statistics": surface.get("statistics"),
        "coordinates": (load_latest_ndvi_surface() or {}).get("mapbox_coordinates"),
        "available": True,
        "nodata": True,
        "nodata_semantics": "transparent outside valid vegetation/moisture pixels",
    }
    return rec


@router.get("/surfaces/ndmi/value")
async def get_ndmi_pixel_value(lon: float, lat: float):
    """Pixel-level NDMI from the supporting 20 m Sentinel-2 index raster."""
    try:
        from app.services.surfaces.index_surfaces import read_index_pixel
        out = read_index_pixel("ndmi", lon, lat)
    except Exception:
        out = None
    if out is None:
        raise HTTPException(status_code=404, detail="No NDMI GeoTIFF for this city")
    return {"metric": "ndmi", "longitude": lon, "latitude": lat, **out,
            "source": "Sentinel-2 NDMI", "resolution_m": out.get("resolution_m")}


@router.get("/surfaces/ndwi/latest")
async def get_latest_ndwi_surface():
    """Standalone NDWI surface, when a dedicated index raster has been published."""
    surface = _manifest_surfaces().get("ndwi")
    if not surface or surface.get("generation_status") != "generated":
        raise HTTPException(status_code=404, detail=f"No NDWI surface has been generated for {get_city().name} yet")
    urls = _layer_urls(surface, "indices")
    return {
        "metric": "ndwi",
        "city": get_city().id,
        **urls,
        "available": True,
        "generated_at": surface.get("generated_at"),
        "source_period": surface.get("source_period"),
        "methodology": "NDWI/MNDWI-based water-health surface",
        "interpretation": surface.get("interpretation"),
        "nodata": True,
        "nodata_semantics": "transparent outside detected water",
    }


@router.get("/surfaces/ndwi/value")
async def get_ndwi_pixel_value(lon: float, lat: float):
    """Pixel-level NDWI from a standalone supporting index raster."""
    surface = _manifest_surfaces().get("ndwi")
    out = _pixel("ndwi", "indices", lon, lat, 3, surface,
                 "Sentinel-2 NDWI")
    if out is None:
        raise HTTPException(status_code=404, detail="No NDWI/MNDWI GeoTIFF for this city")
    return out


@router.get("/surfaces/water-health/value")
async def get_water_health_pixel_value(lon: float, lat: float):
    """Pixel-level Water Health from the scientific GeoTIFF."""
    out = _pixel("water_health", "water-health", lon, lat, 3, load_latest_water_health_surface(),
                 "Sentinel-2 derived Water Health raster")
    if out is None:
        raise HTTPException(status_code=404, detail="No Water Health GeoTIFF for this city")
    return out


def _read_manifest_pixel(metric: str, lon: float, lat: float, digits: int = 3) -> dict | None:
    rec = _manifest_surfaces().get(metric) or {}
    path = _tif_path(rec, metric)
    if path is None:
        return None
    v, nodata = _read_pixel(path, lon, lat)
    return {"value": None if v is None else round(v, digits), "nodata": nodata, "source": rec.get("methodology"),
            "inputs_used": rec.get("inputs_used"), "weights": rec.get("weights")}


# ─────────────────────────────────────────────────────────────────────────────
# one map click: PIXEL -> 300 m CELL -> MUNICIPALITY
# ─────────────────────────────────────────────────────────────────────────────

def _pixel_block(lon: float, lat: float) -> dict[str, Any]:
    from app.services.qc import lst_qc_min_c

    def safe(fn):
        try:
            return fn()
        except Exception:
            return None

    def pick(r):
        if r is None:
            return None
        return {"value": r.get("value"), "nodata": bool(r.get("nodata", True)), "source": r.get("source"),
                "resolution_m": r.get("resolution_m"), "source_period": r.get("source_period")}

    ndvi = pick(safe(lambda: _pixel("ndvi", "ndvi", lon, lat, 3, load_latest_ndvi_surface(), "Sentinel-2 NDVI")))
    lst_raw = safe(lambda: _pixel("lst", "lst", lon, lat, 2, load_latest_lst_surface(),
                                  "Landsat 8/9 Collection 2 Level-2 Surface Temperature", "scale_m"))
    lst = None
    if lst_raw is not None:
        v = lst_raw.get("value")
        lst = {"value_c": v, "nodata": bool(lst_raw.get("nodata", True)),
               "qc_flag": "probable_residual_cloud" if v is not None and v < lst_qc_min_c() else None,
               "source": lst_raw.get("source"), "resolution_m": lst_raw.get("resolution_m"),
               "source_period": lst_raw.get("source_period")}
    wh = pick(safe(lambda: _pixel("water_health", "water-health", lon, lat, 3, load_latest_water_health_surface(),
                                  "Sentinel-2 derived Water Health raster")))
    try:
        from app.services.surfaces.aqi_station_surface import read_aqi_pixel
        aqi = read_aqi_pixel(lon, lat)
    except Exception as exc:  # never fabricate; report why
        aqi = {"value": None, "nodata": True, "available": False, "reason": f"AQI read failed: {exc}"}
    composite = safe(lambda: _read_manifest_pixel("composite", lon, lat, digits=3))
    if composite and not composite.get("nodata"):
        try:
            from app.services.composite_v2 import read_components_pixel
            composite["breakdown"] = read_components_pixel(lon, lat, MANIFEST)
        except Exception:
            pass
    ndmi = ndbi = None
    try:
        from app.services.surfaces.index_surfaces import read_index_pixel
        ndmi, ndbi = read_index_pixel("ndmi", lon, lat), read_index_pixel("ndbi", lon, lat)
    except Exception:
        pass
    return {"longitude": lon, "latitude": lat, "ndmi": ndmi, "ndbi": ndbi, "ndvi": ndvi, "lst": lst, "aqi": aqi,
            "water_health": wh, "composite": composite}


_CELL_SQL = text("""
    WITH point AS (SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), 4326) AS geom),
    matched_cell AS (
        -- 1st priority: the cell containing the point
        SELECT sc.id, sc.cell_code, sc.resolution_m, sc.municipality_name,
               ST_AsBinary(sc.geometry) AS cell_wkb, ST_X(sc.centroid) AS centroid_lon, ST_Y(sc.centroid) AS centroid_lat,
               ST_Distance(sc.centroid::geography, point.geom::geography) AS dist_m, 1 AS match_rank
        FROM spatial_cells sc, point
        WHERE sc.city = :city AND ST_Contains(sc.geometry, point.geom)
        LIMIT 1
    ),
    fallback_cell AS (
        -- 2nd priority: nearest cell within 1 km (clicks on gaps / edges)
        SELECT sc.id, sc.cell_code, sc.resolution_m, sc.municipality_name,
               ST_AsBinary(sc.geometry) AS cell_wkb, ST_X(sc.centroid) AS centroid_lon, ST_Y(sc.centroid) AS centroid_lat,
               ST_Distance(sc.centroid::geography, point.geom::geography) AS dist_m, 2 AS match_rank
        FROM spatial_cells sc, point
        WHERE NOT EXISTS (SELECT 1 FROM matched_cell) AND sc.city = :city
          AND ST_DWithin(sc.centroid::geography, point.geom::geography, 1000)
        ORDER BY sc.centroid <-> point.geom
        LIMIT 1
    )
    SELECT * FROM matched_cell UNION ALL SELECT * FROM fallback_cell LIMIT 1
""")


def _cell_block(db, lon: float, lat: float) -> dict[str, Any] | None:
    row = db.execute(_CELL_SQL, {"lon": lon, "lat": lat, "city": get_city().id}).mappings().one_or_none()
    if not row:
        return None
    cid = row["id"]
    cell: dict[str, Any] = {
        "id": cid, "cell_code": row["cell_code"], "resolution_m": row["resolution_m"],
        "match_type": "contains" if row["match_rank"] == 1 else "nearest",
        "distance_to_centroid_m": round(row["dist_m"], 1),
        "centroid": {"longitude": row["centroid_lon"], "latitude": row["centroid_lat"]},
        "municipality_name_from_cell": row["municipality_name"],
        "anomaly": None,
    }
    # ML snapshot: features and every model's latest result for this cell
    fv = db.execute(text("SELECT feature_values, observed_at FROM engineered_features WHERE cell_id = :c "
                         "ORDER BY observed_at DESC, id DESC LIMIT 1"), {"c": cid}).mappings().one_or_none()
    feats = (fv or {}).get("feature_values") or {}
    cell["features"] = feats.get("raw_values") if isinstance(feats, dict) else None
    cell["feature_sources"] = feats.get("sources") if isinstance(feats, dict) else None
    f = cell["features"] or {}
    cell["metrics_snapshot"] = {"aqi": None if f.get("aqi_idw") is None else int(round(float(f["aqi_idw"]))),
                                "ndvi": f.get("ndvi_mean"), "lst": f.get("lst_mean"),
                                "water_health_score": f.get("wh_mean"),
                                "observed_at": fv["observed_at"].isoformat() if fv else None}
    models = db.execute(text("""
        SELECT DISTINCT ON (model_name) model_name, is_anomaly, anomaly_score, anomaly_type, root_cause, evidence, observed_at
        FROM anomaly_results WHERE cell_id = :c ORDER BY model_name, observed_at DESC, id DESC
    """), {"c": cid}).mappings().all()
    cell["models"] = {r["model_name"]: {"flag": bool(r["is_anomaly"]), "score": r["anomaly_score"],
                                        "type": r["anomaly_type"], "summary": r["root_cause"], "evidence": r["evidence"],
                                        "observed_at": r["observed_at"].isoformat() if r["observed_at"] else None}
                     for r in models}
    iso = cell["models"].get("isolation_forest_cell_v2")
    if iso is not None:
        cell["anomaly"] = {"flag": iso["flag"], "score": iso["score"], "anomaly_type": iso["type"],
                           "root_cause": iso["summary"], "detected_at": iso["observed_at"]}
    # seasonal history (own tables; never mixed with current values)
    try:
        from app.services.history.analytics import cell_history
        cell["history"] = cell_history(db, cid, lat, lon)
    except Exception:
        db.rollback()
        cell["history"] = None
    # The cell's values NOW: means over this 300 m cell of the GeoTIFFs the map is showing, so the
    # panel never shows an older value than the map. The ML snapshot stays in metrics_snapshot.
    try:
        from shapely import wkb as _wkb

        from app.services.ml.cell_features import live_cell_values
        live = live_cell_values(_wkb.loads(bytes(row["cell_wkb"])), (row["centroid_lon"], row["centroid_lat"]))
        cell["metrics"] = {
            "aqi": live["aqi"], "ndvi": live["ndvi"], "ndvi_land": live["ndvi_land"], "lst": live["lst"],
            "water_health_score": live["water_health_score"],
            "composite": (live["composite"] or {}).get("score"), "composite_breakdown": live["composite"],
            "basis": "live: cell mean of the current map GeoTIFFs", "files": live["files"],
            "observed_at": cell["metrics_snapshot"]["observed_at"],
        }
        if live["aqi"] is not None:
            cell["metrics"]["aqi_method"] = "cell mean of the current CPCB IDW surface"
    except Exception as exc:   # keep the snapshot values, say so
        logger.warning("live cell values failed for cell %s: %s", cid, exc)
        cell["metrics"] = {**cell["metrics_snapshot"], "basis": "ML snapshot (live values unavailable)"}
    return cell


@router.get("/analysis/point")
async def get_point_analysis(lon: float, lat: float, db_cm=Depends(_db_cm)):
    """Three-level analysis of a map click: PIXEL (exact GeoTIFF values), 300 m CELL (live cell
    means, ML snapshot, models, history) and MUNICIPALITY (boundary containment)."""
    from shapely.geometry import Point

    from app.services.municipality_boundaries import load_municipality_boundaries

    city = get_city()
    pixel = _pixel_block(lon, lat)
    with db_cm as db:
        cell = _cell_block(db, lon, lat)

    municipality = None
    try:
        p = Point(lon, lat)
        b = next((b for b in load_municipality_boundaries() if b["shapely_geom"].contains(p)), None)
        if b:
            municipality = {"id": b["id"], "name": b["name"], "source": "local GeoJSON boundary containment"}
    except Exception:
        pass
    if municipality is None and cell is not None and cell["municipality_name_from_cell"]:
        municipality = {"id": None, "name": cell["municipality_name_from_cell"],
                        "source": "spatial_cells.municipality_name fallback"}

    place = None
    try:
        from starlette.concurrency import run_in_threadpool

        from app.services.place_names import place_name
        place = await run_in_threadpool(place_name, lon, lat, (municipality or {}).get("name"))
    except Exception:
        place = None

    return {"location": {"longitude": lon, "latitude": lat}, "city": city.id, "city_name": city.name,
            "place": place, "pixel": pixel, "cell": cell, "municipality": municipality}


@router.get("/history/point")
async def get_point_history(lon: float, lat: float, db_cm=Depends(_db_cm)):
    """Seasonal history of the 300 m cell under a point (and its nearest station's AQI)."""
    from app.services.history.analytics import cell_history
    with db_cm as db:
        row = db.execute(text("""
            SELECT id FROM spatial_cells
            WHERE city = :city AND ST_Contains(geometry, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)) LIMIT 1
        """), {"lon": lon, "lat": lat, "city": get_city().id}).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="No analytical cell at this point")
        h = cell_history(db, row, lat, lon)
    if h is None:
        return {"available": False,
                "reason": f"Seasonal history not built yet (run scripts/build_history.py --city {get_city().id})."}
    return {"available": True, **h}


# ─────────────────────────────────────────────────────────────────────────────
# jobs (local or with X-Admin-Token)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/surfaces/aqi/refresh")
async def refresh_aqi_now(background_tasks: BackgroundTasks, request: Request):
    """Rebuild the city's AQI layer now (same as the automatic refresh)."""
    from app.api.admin_guard import require_admin
    from app.services.surfaces import aqi_refresh
    require_admin(request)
    if aqi_refresh._LOCK.locked():
        raise HTTPException(status_code=409, detail="An AQI refresh is already running.")
    background_tasks.add_task(aqi_refresh.refresh, "requested", get_city().id)
    return {"status": "started", "city": get_city().id}


# ─────────────────────────────────────────────────────────────────────────────
# status
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/provenance")
async def get_provenance():
    """Source, dates, resolution, image/station counts and freshness for every layer of the city."""
    from app.services.provenance import all_provenance
    return all_provenance()


@router.get("/health")
async def health_check():
    """Liveness + database reachability (hosting platforms poll this)."""
    from starlette.concurrency import run_in_threadpool

    from app.database import test_database_connection
    try:
        await run_in_threadpool(test_database_connection)
        db = "ok"
    except Exception:
        db = "unreachable"
    return {"status": "healthy", "database": db, "version": "3.0.0", "time": datetime.now(timezone.utc).isoformat()}


@router.get("/system/status")
async def get_system_status(db_cm=Depends(_db_cm)):
    """Read-only pipeline status of the city: cells, ML snapshot, models, layers, history, AQI refresh."""
    from app.services.operational_status import get_operational_status
    with db_cm as db:
        return get_operational_status(db)
