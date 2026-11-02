"""CPCB AQI spatial surface from real OpenAQ v3 CPCB/MPCB monitoring stations.

    OpenAQ v3 -> fresh CPCB/MPCB stations -> CPCB AQI (2014) per station
              -> IDW (k nearest, power p, max distance) -> GeoTIFF -> heatmap PNGs

Honesty rules (from the GeoSense handover):
  * 48-hour freshness limit; stale/future observations excluded.
  * Minimum station requirement. If unmet, NO surface is produced and the manifest
    records `insufficient_coverage` with the station audit, so the API can say so.
  * No AQICN fallback. No satellite proxy is ever labelled as AQI.
  * Pixels farther than MAX_DISTANCE_M from the nearest usable station are NoData.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.transform import from_bounds

from app.services.municipality_boundaries import get_study_region_bounds
from app.services.surfaces.heatmap_render import (
    RenderSpec,
    legend_stops,
    mapbox_coordinates_for,
    render_heatmap,
    save_png,
    sha256,
)

SERVER_ROOT = Path(__file__).resolve().parents[3]
SURFACE_ROOT = SERVER_ROOT / "data" / "surfaces"
AQI_DIR = SURFACE_ROOT / "aqi"
MANIFEST_PATH = SURFACE_ROOT / "manifest.json"
NODATA = -9999.0

GRID_DEG = 0.0025            # ~270 m display/analysis grid for an IDW surface
IDW_K = 4
IDW_POWER = 2.0
MAX_DISTANCE_M = 15000.0     # beyond this the surface is NoData (no extrapolation)
MIN_STATIONS = 3             # minimum fresh CPCB/MPCB stations for a city surface
MIN_NEIGHBOURS = 2           # each pixel needs >=2 stations within MAX_DISTANCE_M
MAX_AGE_HOURS = 48.0
METHODOLOGY = "OpenAQ v3 CPCB/MPCB stations → CPCB National AQI (2014) → IDW"

# CPCB category colours (official AQI bulletin palette)
CPCB_CATEGORIES = (
    (0, 50, "Good", (0, 176, 80)),
    (51, 100, "Satisfactory", (146, 208, 80)),
    (101, 200, "Moderate", (255, 255, 0)),
    (201, 300, "Poor", (255, 153, 0)),
    (301, 400, "Very Poor", (255, 0, 0)),
    (401, 500, "Severe", (192, 0, 0)),
)


def cpcb_category(aqi: float | None) -> dict[str, Any] | None:
    if aqi is None:
        return None
    for lo, hi, name, rgb in CPCB_CATEGORIES:
        if aqi <= hi:
            return {"name": name, "range": [lo, hi], "color": "#%02x%02x%02x" % rgb}
    lo, hi, name, rgb = CPCB_CATEGORIES[-1]
    return {"name": name, "range": [lo, hi], "color": "#%02x%02x%02x" % rgb}


def _haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dl = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def eligible_stations(points: list[dict], now: datetime | None = None) -> tuple[list[dict], list[dict]]:
    """Split station AQI points into (eligible, rejected-with-reason)."""
    now = now or datetime.now(timezone.utc)
    ok, rejected = [], []
    for p in points:
        obs = p.get("observed_at")
        if isinstance(obs, str):
            obs = datetime.fromisoformat(obs.replace("Z", "+00:00"))
        if obs is None:
            rejected.append({**_public(p), "reason": "no timestamp"})
            continue
        if obs.tzinfo is None:
            obs = obs.replace(tzinfo=timezone.utc)
        age_h = (now - obs).total_seconds() / 3600.0
        if age_h < -0.25:
            rejected.append({**_public(p), "reason": "future timestamp"})
        elif age_h > MAX_AGE_HOURS:
            rejected.append({**_public(p), "reason": f"stale ({age_h:.0f} h old)"})
        elif not p.get("is_cpcb_mpcb", False):
            rejected.append({**_public(p), "reason": "not CPCB/MPCB-backed"})
        elif p.get("aqi") is None or not math.isfinite(float(p["aqi"])):
            rejected.append({**_public(p), "reason": "CPCB AQI not computable"})
        else:
            ok.append({**p, "observed_at": obs, "age_hours": round(age_h, 2)})
    return ok, rejected


def _public(p: dict) -> dict:
    obs = p.get("observed_at")
    return {
        "station_id": p.get("station_id"),
        "station_name": p.get("station_name"),
        "lat": p.get("lat"),
        "lon": p.get("lon"),
        "provider": p.get("provider"),
        "aqi": None if p.get("aqi") is None else int(round(float(p["aqi"]))),
        "dominant_pollutant": p.get("dominant_pollutant"),
        "observed_at": obs.isoformat() if isinstance(obs, datetime) else obs,
        "freshness": p.get("freshness"),
        "age_hours": p.get("age_hours"),
        "category": cpcb_category(None if p.get("aqi") is None else float(p["aqi"])),
        "sub_indices": p.get("sub_indices"),
    }


def idw_grid(stations: list[dict], bounds: tuple[float, float, float, float], step: float = GRID_DEG):
    """Vectorised IDW over a regular lon/lat grid. Returns (grid, nearest_m, n_used, transform)."""
    west, south, east, north = bounds
    width = int(math.ceil((east - west) / step))
    height = int(math.ceil((north - south) / step))
    transform = from_bounds(west, south, west + width * step, south + height * step, width, height)
    cols = west + (np.arange(width) + 0.5) * step
    rows = (south + height * step) - (np.arange(height) + 0.5) * step
    lon, lat = np.meshgrid(cols, rows)

    s_lat = np.array([s["lat"] for s in stations], dtype="float64")
    s_lon = np.array([s["lon"] for s in stations], dtype="float64")
    s_val = np.array([float(s["aqi"]) for s in stations], dtype="float64")

    d = _haversine_m(lat[..., None], lon[..., None], s_lat, s_lon)  # H,W,S
    order = np.argsort(d, axis=-1)[..., :IDW_K]
    dk = np.take_along_axis(d, order, axis=-1)
    vk = s_val[order]
    within = dk <= MAX_DISTANCE_M
    n_used = within.sum(axis=-1)
    w = np.where(within, 1.0 / np.maximum(dk, 1.0) ** IDW_POWER, 0.0)
    wsum = w.sum(axis=-1)
    est = np.divide((w * vk).sum(axis=-1), wsum, out=np.full(wsum.shape, NODATA), where=wsum > 0)
    est = np.where(n_used >= MIN_NEIGHBOURS, est, NODATA).astype("float32")
    return est, dk[..., 0].astype("float32"), n_used.astype("int16"), transform


def _write_manifest_record(record: dict, manifest_path: Path) -> None:
    current = {"version": 1, "surfaces": {}}
    if manifest_path.exists():
        current = json.loads(manifest_path.read_text(encoding="utf-8"))
    surfaces = current.setdefault("surfaces", {})
    old = surfaces.get("aqi")
    # Retire the old Sentinel-5P NO2 "AQI proxy": it is not CPCB AQI.
    if old and "S5P" in str(old.get("dataset", "")):
        surfaces["no2_s5p_column_retired"] = {**old, "retired_reason": "Satellite NO2 column is not CPCB AQI; never served as AQI."}
    surfaces["aqi"] = record
    tmp = manifest_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, indent=2, sort_keys=True, default=str), encoding="utf-8")
    tmp.replace(manifest_path)


def build_aqi_surface(station_points: list[dict], *, manifest_path: Path = MANIFEST_PATH,
                      out_dir: Path = AQI_DIR, now: datetime | None = None) -> dict[str, Any]:
    """Create the AQI surface or record honestly why it cannot be created."""
    now = now or datetime.now(timezone.utc)
    stations, rejected = eligible_stations(station_points, now)
    audit = {
        "stations_received": len(station_points),
        "stations_eligible": len(stations),
        "stations_rejected": rejected,
        "freshness_limit_hours": MAX_AGE_HOURS,
        "minimum_stations": MIN_STATIONS,
    }
    base = {
        "metric": "aqi",
        "methodology": METHODOLOGY,
        "source": "OpenAQ v3 (CPCB / MPCB continuous ambient monitoring stations)",
        "aqi_standard": "CPCB National Air Quality Index (2014)",
        "generated_at": now.isoformat(),
        "stations": [_public(s) for s in stations],
        "audit": audit,
        "interpolation": {"method": "IDW", "k": IDW_K, "power": IDW_POWER,
                          "max_distance_m": MAX_DISTANCE_M, "min_neighbours": MIN_NEIGHBOURS},
    }
    if len(stations) < MIN_STATIONS:
        record = {**base, "generation_status": "insufficient_coverage", "available": False,
                  "reason": f"Only {len(stations)} fresh (≤48 h) CPCB/MPCB station(s) with computable CPCB AQI "
                            f"(need {MIN_STATIONS}). No AQI surface was produced and no proxy is shown in its place.",
                  "operator_hint": "Run: python scripts/generate_aqi_station_surface.py --cells "
                                   "(needs OPENAQ_AQI_KEY and internet)."}
        _write_manifest_record(record, manifest_path)
        return record

    bounds = get_study_region_bounds()
    grid, nearest, n_used, transform = idw_grid(stations, bounds)
    ts = max(s["observed_at"] for s in stations).strftime("%Y%m%dT%H%M%SZ")
    out_dir.mkdir(parents=True, exist_ok=True)
    tif = out_dir / f"aqi_cpcb_idw_{ts}.tif"
    with rasterio.open(tif, "w", driver="GTiff", height=grid.shape[0], width=grid.shape[1], count=1,
                       dtype="float32", crs="EPSG:4326", transform=transform, nodata=NODATA,
                       compress="deflate") as dst:
        dst.write(grid, 1)
        dst.update_tags(methodology=METHODOLOGY, stations=str(len(stations)))

    valid = grid != NODATA
    knots = [25, 75, 150, 250, 350, 450]
    spec = RenderSpec(metric="aqi", stops_rgb=[c[3] for c in CPCB_CATEGORIES], knot_values=knots,
                      stop_labels=[c[2] for c in CPCB_CATEGORIES], downsample=1,
                      sharp_sigma=1.2, glow_sigma=4.0, halo_sigma=9.0,
                      sharp_alpha=200, glow_alpha=120, halo_alpha=70)
    out = render_heatmap(grid, valid, transform, spec)
    names, sums = {}, {}
    for k in ("sharp", "glow", "halo"):
        names[k] = f"{tif.stem}_{k}.png"
        sums[k] = save_png(out[k], out_dir / names[k])

    vals = grid[valid]
    record = {
        **base,
        "generation_status": "generated",
        "available": True,
        "dataset": "OpenAQ v3",
        "source_timestamp": max(s["observed_at"] for s in stations).isoformat(),
        "geotiff_filename": f"aqi/{tif.name}",
        "png_filename": f"aqi/{names['sharp']}",
        "sharp_png_filename": f"aqi/{names['sharp']}",
        "glow_png_filename": f"aqi/{names['glow']}",
        "halo_png_filename": f"aqi/{names['halo']}",
        "files": {"geotiff": tif.name, "png": names["sharp"], "sharp_png": names["sharp"],
                  "glow_png": names["glow"], "halo_png": names["halo"]},
        "checksums": {"geotiff_sha256": sha256(tif), "png_sha256": sums["sharp"],
                      "sharp_png_sha256": sums["sharp"], "glow_png_sha256": sums["glow"],
                      "halo_png_sha256": sums["halo"]},
        "mapbox_coordinates": mapbox_coordinates_for(transform, grid.shape),
        "interpretation": "Interpolated CPCB AQI between real monitoring stations. Values between stations are "
                          "estimates (IDW), not measurements; pixels > 15 km from stations are NoData.",
        "nodata_value": NODATA,
        "nodata_semantics": "transparent; fewer than 2 stations within 15 km, or outside study region",
        "aqi_min": float(vals.min()) if vals.size else None,
        "aqi_max": float(vals.max()) if vals.size else None,
        "aqi_mean": float(vals.mean()) if vals.size else None,
        "visualization": {"stops": legend_stops(spec), "palette": "CPCB official category colours",
                          "legend": {"left_label": "GOOD · 0", "right_label": "SEVERE · 500",
                                     "range": {"min": 0, "max": 500}},
                          "study_region_clipped": True, "mask_applied_after_blur": True},
    }
    _write_manifest_record(record, manifest_path)
    return record


def read_aqi_pixel(lon: float, lat: float, manifest_path: Path = MANIFEST_PATH) -> dict[str, Any]:
    """Exact IDW pixel read from the AQI GeoTIFF, with nearest-station provenance."""
    if not manifest_path.exists():
        return {"value": None, "nodata": True, "available": False, "reason": "no manifest"}
    rec = json.loads(manifest_path.read_text(encoding="utf-8")).get("surfaces", {}).get("aqi") or {}
    if rec.get("generation_status") != "generated":
        return {"value": None, "nodata": True, "available": False,
                "reason": rec.get("reason", "AQI surface not generated (no fresh CPCB/MPCB coverage)")}
    tif = SURFACE_ROOT / rec["geotiff_filename"]
    with rasterio.open(tif) as ds:
        b = ds.bounds
        if not (b.left <= lon <= b.right and b.bottom <= lat <= b.top):
            return {"value": None, "nodata": True, "available": True, "reason": "outside surface"}
        r, c = ds.index(lon, lat)
        v = float(ds.read(1, window=((r, r + 1), (c, c + 1)))[0, 0])
    nodata = v == NODATA or not math.isfinite(v)
    stations = rec.get("stations", [])
    nearest = None
    if stations:
        d = [(_haversine_m(lat, lon, s["lat"], s["lon"]), s) for s in stations]
        dist, s = min(d, key=lambda x: x[0])
        nearest = {"station_name": s["station_name"], "distance_m": round(float(dist)), "aqi": s["aqi"],
                   "observed_at": s["observed_at"], "dominant_pollutant": s.get("dominant_pollutant"),
                   "sub_indices": s.get("sub_indices")}
    return {
        "value": None if nodata else int(round(v)),
        "nodata": nodata,
        "available": True,
        "category": None if nodata else cpcb_category(v),
        "source": METHODOLOGY,
        "estimate_type": "IDW interpolation between stations (estimate, not a direct measurement)",
        "nearest_station": nearest,
        "source_timestamp": rec.get("source_timestamp"),
    }
