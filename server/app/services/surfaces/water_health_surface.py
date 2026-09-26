"""Static Sentinel-2 Water Health surface artifacts for Mapbox.

This module reuses GeoSense's established Sentinel-2 preprocessing and writes
derived files only. It neither reads zone averages as pixels nor writes to the
database. The frozen zone geometry is used solely to obtain the existing study
extent for a rectangular satellite export.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any
import zipfile

import ee
import numpy as np
from PIL import Image, ImageFilter

_RASTERIO_PROJ_DATA = Path(sys.prefix) / "Lib" / "site-packages" / "rasterio" / "proj_data"
if _RASTERIO_PROJ_DATA.is_dir():
    os.environ["PROJ_LIB"] = str(_RASTERIO_PROJ_DATA)
    os.environ["PROJ_DATA"] = str(_RASTERIO_PROJ_DATA)
import rasterio
from rasterio.features import rasterize as rio_rasterize
from sqlalchemy import text
import requests

from app.database import engine
from app.services.municipality_boundaries import load_municipality_boundaries, MunicipalityBoundaryError
from gee.gee_client import initialize_ee
from gee.ingest_ndvi_ndwi import (
    COMPOSITE_WINDOW_DAYS,
    S2_DATASET,
    add_indices,
    mask_s2_sr,
    source_context,
)

CRS = "EPSG:4326"
NODATA_VALUE = -9999.0
SCALE_METERS = 10
METHODOLOGY = "Sentinel-2 median composite Water Health"
WH_GLOW_THRESHOLD = 0.60
SERVER_ROOT = Path(__file__).resolve().parents[3]
SURFACE_ROOT = SERVER_ROOT / "data" / "surfaces"
MANIFEST_PATH = SURFACE_ROOT / "manifest.json"


def mapbox_coordinates(bounds: tuple[float, float, float, float]) -> list[list[float]]:
    west, south, east, north = bounds
    return [[west, north], [east, north], [east, south], [west, south]]


def get_study_region_mask(width: int, height: int, transform,
                           bounds: tuple[float, float, float, float]) -> np.ndarray | None:
    """Build a uint8 alpha mask (255=inside study region, 0=outside) for WH rasters.

    Union of Mumbai + Thane + Mira-Bhayandar local GeoJSON boundaries.
    Rasterised to the same (width, height, transform) as the target raster.
    Returns None if boundaries are unavailable so builds remain backward-compatible.
    """
    from shapely.geometry import mapping
    try:
        boundaries = load_municipality_boundaries()
    except (MunicipalityBoundaryError, Exception):
        return None

    west, south, east, north = bounds
    out_shape = (height, width)
    shapes = []
    for b in boundaries:
        try:
            geom = b["shapely_geom"]
            from shapely.geometry import box as shapely_box
            raster_box = shapely_box(west, south, east, north)
            clipped = geom.intersection(raster_box)
            if clipped.is_empty:
                continue
            shapes.append((mapping(clipped), 255))
        except Exception:
            continue

    if not shapes:
        return None

    try:
        mask = rio_rasterize(
            shapes,
            out_shape=out_shape,
            transform=transform,
            fill=0,
            all_touched=True,
            dtype="uint8",
        )
    except Exception:
        return None
    return mask.astype(np.uint8)


def apply_study_region_mask(rgba_img: np.ndarray, mask: np.ndarray | None) -> np.ndarray:
    """Multiply alpha of an HxWx4 RGBA array by the study-region mask."""
    if mask is None:
        return rgba_img
    if rgba_img.shape[:2] != mask.shape:
        return rgba_img
    out = rgba_img.copy()
    out[:, :, 3] = (out[:, :, 3].astype(np.uint16) * mask.astype(np.uint16) // 255).astype(np.uint8)
    return out


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_manifest(record: dict[str, Any], manifest_path: Path) -> None:
    current: dict[str, Any] = {"version": 1, "surfaces": {}}
    if manifest_path.exists():
        try:
            current = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Existing surface manifest is invalid: {manifest_path}") from exc
    current.setdefault("version", 1)
    current.setdefault("surfaces", {})["water_health"] = record
    temporary = manifest_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(manifest_path)


def get_water_health_export_bounds() -> tuple[float, float, float, float]:
    """Read the established GeoSense analysis extent without changing zones."""
    statement = text("""
        SELECT ST_XMin(extent) AS west, ST_YMin(extent) AS south,
               ST_XMax(extent) AS east, ST_YMax(extent) AS north
        FROM (SELECT ST_Extent(geometry)::box3d AS extent FROM spatial_cells) cell_extent
    """)
    with engine.connect() as connection:
        row = connection.execute(statement).mappings().one()
    bounds = tuple(float(row[key]) for key in ("west", "south", "east", "north"))
    if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
        raise ValueError("GeoSense analysis extent is invalid")
    return bounds


def build_water_health_composite(*, start_date: str, end_date: str, bounds: tuple[float, float, float, float]):
    """Build exactly the established cloud-masked Sentinel-2 Water Health composite."""
    initialize_ee()
    region = ee.Geometry.Rectangle(list(bounds), proj=CRS, geodesic=False)
    collection = (
        ee.ImageCollection(S2_DATASET)
        .filterDate(start_date, end_date)
        .filterBounds(region)
        .select(["B3", "B4", "B5", "B8", "B11", "QA60"])
        .map(mask_s2_sr)
        .map(add_indices)
    )
    image_count = int(collection.size().getInfo())
    if image_count == 0:
        raise ValueError("No Sentinel-2 images found for the configured Water Health composite window")
    composite = collection.median().select(["NDVI", "NDWI", "MNDWI", "NDCI_PROXY", "TURBIDITY_PROXY"]).clip(region)

    water_mask = composite.select("MNDWI").gte(0.0)

    algal_stress = composite.select("NDCI_PROXY").add(1.0).divide(2.0).clamp(0.0, 1.0)
    algal_health = ee.Image(1.0).subtract(algal_stress)

    suspended_stress = composite.select("TURBIDITY_PROXY").add(1.0).divide(2.0).clamp(0.0, 1.0)
    suspended_health = ee.Image(1.0).subtract(suspended_stress)

    water_health = algal_health.add(suspended_health).divide(2.0).clamp(0.0, 1.0).rename("WATER_HEALTH")
    water_health = water_health.updateMask(water_mask)

    return water_health.clip(region), region, image_count


def _extract_tiff_from_zip(archive_path: Path) -> Path:
    """If archive_path is a zip, extract its single TIFF and return the new path;
    otherwise return archive_path unchanged."""
    if not zipfile.is_zipfile(archive_path):
        return archive_path
    with zipfile.ZipFile(archive_path) as archive:
        tiffs = [m for m in archive.namelist() if m.lower().endswith((".tif", ".tiff"))]
        if len(tiffs) != 1:
            raise ValueError("Earth Engine download did not contain exactly one Water Health GeoTIFF")
        extracted = archive_path.parent / Path(tiffs[0]).name
        with archive.open(tiffs[0]) as src, extracted.open("wb") as dst:
            shutil.copyfileobj(src, dst)
    archive_path.unlink()
    return extracted


def _tile_download(image: Any, tile_region: Any, dest: Path) -> Path:
    """Download one tile at SCALE_METERS with retry for transient GEE 503s."""
    import time as _time
    url = image.getDownloadURL({
        "scale": SCALE_METERS,
        "crs": CRS,
        "region": tile_region,
        "format": "GEO_TIFF",
        "filePerBand": False,
    })
    last_error = None
    for attempt in range(5):
        try:
            response = requests.get(url, timeout=240)
            response.raise_for_status()
            dest.write_bytes(response.content)
            return _extract_tiff_from_zip(dest)
        except requests.HTTPError as exc:
            last_error = exc
            status = exc.response.status_code if exc.response is not None else 0
            if status >= 500 and attempt < 4:
                wait_s = 2 ** attempt + attempt
                print(f"  GEE tile download returned {status}; retrying in {wait_s}s (attempt {attempt+1}/5)")
                _time.sleep(wait_s)
                if dest.exists():
                    dest.unlink()
                continue
            raise
    raise last_error  # pragma: no cover


def _download_geotiff(image: Any, region: Any, destination: Path) -> None:
    """Download a Water Health GeoTIFF at native 10 m resolution.

    Uses a 2x1 horizontal tile split to remain under GEE's ~48 MB per-request
    body limit, then mosaics the result with rasterio. Scientific pixel
    values, CRS, transform and coverage are preserved exactly at 10 m."""
    from rasterio.merge import merge as rio_merge

    coords = region.coordinates().getInfo()[0]
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    west, east = min(xs), max(xs)
    south, north = min(ys), max(ys)
    mid_x = (west + east) / 2.0

    tile_defs = [
        ("tile_w", ee.Geometry.Rectangle([west, south, mid_x, north], proj=CRS, geodesic=False)),
        ("tile_e", ee.Geometry.Rectangle([mid_x, south, east, north], proj=CRS, geodesic=False)),
    ]

    with tempfile.TemporaryDirectory(prefix="wh_tiles_") as tmp_dir:
        tmp = Path(tmp_dir)
        tile_paths: list[Path] = []
        for label, tile_reg in tile_defs:
            raw_path = tmp / f"{label}.raw"
            tif_path = _tile_download(image, tile_reg, raw_path)
            tile_paths.append(tif_path)

        datasets = [rasterio.open(p) for p in tile_paths]
        try:
            merged_arr, merged_transform = rio_merge(
                datasets,
                nodata=NODATA_VALUE,
            )
            out_meta = datasets[0].meta.copy()
            out_meta.update({
                "height": merged_arr.shape[1],
                "width": merged_arr.shape[2],
                "count": merged_arr.shape[0],
                "transform": merged_transform,
                "crs": CRS,
                "nodata": NODATA_VALUE,
            })
            with rasterio.open(destination, "w", **out_meta) as dst:
                dst.write(merged_arr)
        finally:
            for ds in datasets:
                ds.close()


def _water_health_display_percentile_map(valid_values: np.ndarray) -> dict[str, float]:
    """Compute percentile breakpoints for Water Health visualization-only colouring.

    Scientific values in the GeoTIFF, returned by /value and shown in panels,
    are never changed by this mapping.  The percentiles below are ONLY used to
    spread the clustered 0.41→0.49 Water Health distribution across a full
    multi-colour heatmap so that small but real differences in water body
    condition are visibly distinguishable on the map.

    Returns a dict with raw_value → display_t (0..1) breakpoints.
    """
    if valid_values.size == 0:
        return {
            "p05_raw": 0.0, "p25_raw": 0.25, "p50_raw": 0.5,
            "p75_raw": 0.75, "p95_raw": 1.0,
            "raw_min": 0.0, "raw_max": 1.0,
        }
    return {
        "p05_raw": float(np.percentile(valid_values, 5)),
        "p25_raw": float(np.percentile(valid_values, 25)),
        "p50_raw": float(np.percentile(valid_values, 50)),
        "p75_raw": float(np.percentile(valid_values, 75)),
        "p95_raw": float(np.percentile(valid_values, 95)),
        "raw_min": float(valid_values.min()),
        "raw_max": float(valid_values.max()),
    }


def _wh_raw_to_display_t(value: float, pct: dict[str, float]) -> float:
    """Project a raw Water Health value (0..1) to a display_t (0..1).

    Mapping:
      raw <= P05   → 0.00  (magenta/red — most degraded water visible)
      raw == P25   → 0.20  (orange)
      raw == P50   → 0.45  (yellow)
      raw == P75   → 0.70  (lime / green)
      raw >= P95   → 1.00  (teal / cyan — healthiest)

    This is a pure visualization mapping; it never feeds back into the
    scientific GeoTIFF, the /value API, or the right-hand panel.
    """
    p05 = pct["p05_raw"]; p25 = pct["p25_raw"]; p50 = pct["p50_raw"]
    p75 = pct["p75_raw"]; p95 = pct["p95_raw"]
    if value <= p05:
        return 0.0 + max(0.0, (value - pct["raw_min"]) / max(1e-6, p05 - pct["raw_min"])) * 0.05
    if value <= p25:
        return 0.05 + (value - p05) / max(1e-6, p25 - p05) * (0.25 - 0.05)
    if value <= p50:
        return 0.25 + (value - p25) / max(1e-6, p50 - p25) * (0.50 - 0.25)
    if value <= p75:
        return 0.50 + (value - p50) / max(1e-6, p75 - p50) * (0.75 - 0.50)
    if value <= p95:
        return 0.75 + (value - p75) / max(1e-6, p95 - p75) * (1.00 - 0.75)
    return 1.0


def _water_health_rgba(value: float, pct: dict[str, float] | None = None) -> tuple[int, int, int, int]:
    """RGBA for one Water Health pixel — vibrant environmental heatmap.

    IMPORTANT:
    * If `pct` is provided, raw values are projected to display_t via
      percentile breakpoints (visualization-only spread).
    * If `pct` is None, the raw 0→1 value is used directly (backward compat).
    * Scientific pixel values are NEVER modified; only display colour changes.

    Alpha:
      - NoData / non-water (-9999) → alpha=0
      - WH < 0.05 → alpha=0 (below this, MNDWI mask already excludes non-water)
      - 0.05 → 0.50: fade in via t^1.6 ramp up to alpha plateau 220
      - ≥ 0.50: plateau at 220

    Color progression (display_t → colour):
      0.00 magenta      degraded
      0.18 red
      0.38 orange
      0.58 yellow
      0.78 lime / green
      1.00 teal / cyan  healthier
    """
    ALPHA_ZERO_BELOW = 0.05
    ALPHA_FULL_ABOVE = 0.50
    ALPHA_PLATEAU = 220

    if not np.isfinite(value) or value == NODATA_VALUE:
        return (0, 0, 0, 0)
    if value < ALPHA_ZERO_BELOW:
        return (0, 0, 0, 0)
    if value < ALPHA_FULL_ABOVE:
        t_alpha = (value - ALPHA_ZERO_BELOW) / (ALPHA_FULL_ABOVE - ALPHA_ZERO_BELOW)
        alpha = int(round((t_alpha ** 1.6) * ALPHA_PLATEAU))
    else:
        alpha = ALPHA_PLATEAU

    # Display mapping: percentile-based (visualization-only) if available
    if pct is not None:
        disp_t = float(_wh_raw_to_display_t(value, pct))
    else:
        disp_t = float(max(0.0, min(1.0, value)))

    colour_stops: tuple[tuple[float, tuple[int, int, int]], ...] = (
        (0.00, (221,  38, 154)),
        (0.18, (255,  59,  59)),
        (0.38, (255, 140,   0)),
        (0.58, (255, 210,  60)),
        (0.78, ( 92, 214,  72)),
        (1.00, ( 18, 200, 212)),
    )
    lo_val, lo_rgb = colour_stops[0]
    hi_val, hi_rgb = colour_stops[-1]
    clamped = max(lo_val, min(hi_val, disp_t))
    r, g, b = lo_rgb
    for (left, c0), (right, c1) in zip(colour_stops, colour_stops[1:]):
        if clamped <= right:
            t_seg = (clamped - left) / (right - left) if right > left else 0.0
            r = int(round(c0[0] + (c1[0] - c0[0]) * t_seg))
            g = int(round(c0[1] + (c1[1] - c0[1]) * t_seg))
            b = int(round(c0[2] + (c1[2] - c0[2]) * t_seg))
            break
    return (r, g, b, alpha)


def water_health_to_rgba(values: np.ndarray, pct: dict[str, float] | None = None) -> np.ndarray:
    """Vectorised Water Health → vibrant multi-colour heatmap RGBA.

    This is pure display-only rendering.  The raw Water Health values in the
    GeoTIFF and returned by /api/analysis/point are completely unchanged.

    When `pct` is supplied the distribution is spread via percentile
    breakpoints so the tightly-clustered 0.41–0.49 water body values span
    the full magenta→teal heatmap visibly.
    """
    STOP_DISP_T = np.array([0.00, 0.18, 0.38, 0.58, 0.78, 1.00], dtype=np.float32)
    STOP_R = np.array([221, 255, 255, 255,  92,  18], dtype=np.float32)
    STOP_G = np.array([ 38,  59, 140, 210, 214, 200], dtype=np.float32)
    STOP_B = np.array([154,  59,   0,  60,  72, 212], dtype=np.float32)
    ALPHA_ZERO = np.float32(0.05)
    ALPHA_FULL = np.float32(0.50)
    ALPHA_MAX  = np.float32(220.0)

    valid   = np.isfinite(values) & (values != NODATA_VALUE)
    h, w = values.shape
    v_flat = values.ravel()

    # Build display_t (percentile spread if pct provided, else raw)
    if pct is not None and valid.any():
        raw = np.where(valid.ravel(), v_flat, np.float32(pct["p50_raw"]))
        p05 = np.float32(pct["p05_raw"]); p25 = np.float32(pct["p25_raw"]); p50 = np.float32(pct["p50_raw"])
        p75 = np.float32(pct["p75_raw"]); p95 = np.float32(pct["p95_raw"])
        raw_min = np.float32(pct["raw_min"]); raw_max = np.float32(pct["raw_max"])
        span1 = np.float32(max(1e-6, p05 - raw_min))
        span2 = np.float32(max(1e-6, p25 - p05))
        span3 = np.float32(max(1e-6, p50 - p25))
        span4 = np.float32(max(1e-6, p75 - p50))
        span5 = np.float32(max(1e-6, p95 - p75))
        span6 = np.float32(max(1e-6, raw_max - p95))
        disp = np.zeros_like(raw, dtype=np.float32)
        m1 = raw <= p05
        disp = np.where(m1, (raw - raw_min) / span1 * np.float32(0.05), disp)
        m2 = ~m1 & (raw <= p25)
        disp = np.where(m2, np.float32(0.05) + (raw - p05) / span2 * np.float32(0.20), disp)
        m3 = ~m1 & ~m2 & (raw <= p50)
        disp = np.where(m3, np.float32(0.25) + (raw - p25) / span3 * np.float32(0.25), disp)
        m4 = ~m1 & ~m2 & ~m3 & (raw <= p75)
        disp = np.where(m4, np.float32(0.50) + (raw - p50) / span4 * np.float32(0.25), disp)
        m5 = ~m1 & ~m2 & ~m3 & ~m4 & (raw <= p95)
        disp = np.where(m5, np.float32(0.75) + (raw - p75) / span5 * np.float32(0.25), disp)
        m6 = ~m1 & ~m2 & ~m3 & ~m4 & ~m5
        disp = np.where(m6, np.float32(1.0), disp)
        disp_t = np.clip(disp, 0.0, 1.0)
    else:
        disp_t = np.clip(np.where(valid, v_flat, np.float32(0.0)), 0.0, 1.0)

    clamped = disp_t.ravel()

    r_acc = np.zeros(h * w, np.float32)
    g_acc = np.zeros(h * w, np.float32)
    b_acc = np.zeros(h * w, np.float32)
    for i in range(len(STOP_DISP_T) - 1):
        lo, hi = STOP_DISP_T[i], STOP_DISP_T[i + 1]
        seg = (clamped >= lo) & (clamped <= hi)
        t_seg = np.where(seg, (clamped - lo) / (hi - lo), 0.0)
        r_acc += seg * (STOP_R[i] + (STOP_R[i + 1] - STOP_R[i]) * t_seg)
        g_acc += seg * (STOP_G[i] + (STOP_G[i + 1] - STOP_G[i]) * t_seg)
        b_acc += seg * (STOP_B[i] + (STOP_B[i + 1] - STOP_B[i]) * t_seg)

    alpha_f = np.where(
        v_flat < ALPHA_ZERO, 0.0,
        np.where(
            v_flat < ALPHA_FULL,
            (((v_flat - ALPHA_ZERO) / (ALPHA_FULL - ALPHA_ZERO)).clip(0.0, 1.0) ** 1.6) * ALPHA_MAX,
            ALPHA_MAX,
        ),
    )
    alpha_f = np.where(valid.ravel(), alpha_f, 0.0)

    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[:, :, 0] = np.clip(r_acc, 0, 255).reshape(h, w).astype(np.uint8)
    rgba[:, :, 1] = np.clip(g_acc, 0, 255).reshape(h, w).astype(np.uint8)
    rgba[:, :, 2] = np.clip(b_acc, 0, 255).reshape(h, w).astype(np.uint8)
    rgba[:, :, 3] = np.clip(alpha_f, 0, 255).reshape(h, w).astype(np.uint8)
    return rgba


def _blur_rgba(rgba: np.ndarray, radius: float) -> np.ndarray:
    img = Image.fromarray(rgba, mode="RGBA")
    r, g, b, a = img.split()
    r2 = r.filter(ImageFilter.GaussianBlur(radius=radius))
    g2 = g.filter(ImageFilter.GaussianBlur(radius=radius))
    b2 = b.filter(ImageFilter.GaussianBlur(radius=radius))
    a2 = a.filter(ImageFilter.GaussianBlur(radius=radius))
    return np.array(Image.merge("RGBA", (r2, g2, b2, a2))).astype(np.uint8)


def generate_water_health_three_layer(
    values: np.ndarray,
    sharp_path: Path,
    glow_path: Path,
    halo_path: Path,
    study_mask: np.ndarray | None,
    pct: dict[str, float] | None,
) -> None:
    """Generate three Water Health visualization layers.

    ORDER (critical — prevents halo bleed outside study-region boundary):
        1. scientific values → colour (via percentile-display mapping)
        2. blur → glow / halo
        3. apply study-region mask to ALL three layers (multiply alpha)
        4. save PNGs
    """
    sharp_rgba = water_health_to_rgba(values, pct=pct)

    glow_rgba = _blur_rgba(sharp_rgba, radius=3.0)
    halo_rgba = _blur_rgba(sharp_rgba, radius=8.0)

    # Widen halo alpha — broader soft heatmap blob
    halo_rgba = halo_rgba.copy()
    halo_rgba[:, :, 3] = np.clip(halo_rgba[:, :, 3].astype(np.uint16) * 205 // 255, 0, 255).astype(np.uint8)

    # --- 3. Apply study-region mask LAST so no blur bleeds outside ---
    sharp_rgba = apply_study_region_mask(sharp_rgba, study_mask)
    glow_rgba  = apply_study_region_mask(glow_rgba,  study_mask)
    halo_rgba  = apply_study_region_mask(halo_rgba,  study_mask)

    Image.fromarray(sharp_rgba, mode="RGBA").save(sharp_path, "PNG", compress_level=6)
    Image.fromarray(glow_rgba,  mode="RGBA").save(glow_path,  "PNG", compress_level=6)
    Image.fromarray(halo_rgba,  mode="RGBA").save(halo_path,  "PNG", compress_level=6)


def publish_water_health_geotiff(
    source_path: Path,
    *,
    start_date: str,
    end_date: str,
    image_count: int,
    output_root: Path = SURFACE_ROOT,
) -> dict[str, Any]:
    """Validate a real GEE export and publish canonical TIFF + 3 heatmap PNG layers.

    Visualisation layers:
        HALO  (wide soft glow, r=8)
        GLOW  (medium blur, r=3)
        SHARP (pixel-exact coloured raster)

    Colour mapping uses PERCENTILE-BASED display spread (raw values clustered
    tightly around 0.4-0.5) via ``_water_health_display_percentile_map`` so that
    adjacent health bins pop with distinct saturated colours while the
    scientific GeoTIFF pixel values remain 100% unchanged.

    All three layers are clipped/masked to the study-region union (Mumbai +
    Thane + Mira-Bhayandar) AFTER blurring, so the glow/halo cannot bleed
    outside the municipal boundaries.
    """
    context = source_context(start_date, end_date)
    with rasterio.open(source_path) as source:
        if source.count != 1:
            raise ValueError("Water Health export must contain exactly one raster band")
        if source.crs is None or source.crs.to_string() != CRS:
            raise ValueError(f"Water Health export must use {CRS}; received {source.crs}")
        values = source.read(1).astype(np.float32)
        mask = source.read_masks(1) > 0
        nodata = source.nodata
        if nodata is not None:
            mask &= values != nodata
        mask &= values != NODATA_VALUE
        finite_valid = np.isfinite(values)
        valid = mask & finite_valid
        if valid.any():
            v_min = float(values[valid].min())
            v_max = float(values[valid].max())
            if v_min < -1e-3 or v_max > 1.0 + 1e-3:
                raise ValueError(
                    f"Water Health export contains values outside the valid 0..1 range: "
                    f"min={v_min} max={v_max}"
                )
            clamped_valid = np.clip(values[valid], 0.0, 1.0)
            values = values.copy()
            values[valid] = clamped_valid
        output_values = np.where(valid, values, NODATA_VALUE).astype(np.float32)
        bounds = (source.bounds.left, source.bounds.bottom, source.bounds.right, source.bounds.top)
        transform = source.transform
        width, height = source.width, source.height

    # --- Study-region mask: rasterize union of MMB boundaries to this grid ---
    study_mask = get_study_region_mask(width, height, transform, bounds)

    # --- Percentile breakpoints for visualisation-only spread ---
    valid_values = output_values[output_values != NODATA_VALUE]
    pct = _water_health_display_percentile_map(valid_values)

    output_dir = output_root / "water-health"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
    stamp = timestamp.strftime("%Y%m%dT%H%M%SZ")
    geotiff_path = output_dir / f"wh_{stamp}.tif"
    sharp_path  = output_dir / f"wh_{stamp}.png"
    glow_path   = output_dir / f"wh_{stamp}_glow.png"
    halo_path   = output_dir / f"wh_{stamp}_halo.png"

    with rasterio.open(
        geotiff_path, "w", driver="GTiff", height=height, width=width, count=1,
        dtype="float32", crs=CRS, transform=transform, nodata=NODATA_VALUE, compress="deflate",
    ) as output:
        output.write(output_values, 1)
        output.update_tags(
            metric="water_health", source="Google Earth Engine / Sentinel-2",
            dataset=S2_DATASET, methodology=METHODOLOGY,
            window_start=start_date, window_end=end_date,
            cloud_mask=context["cloud_mask"],
            mndwi_threshold=str(context["mndwi_threshold"]),
            ndci_proxy_formula=context["indices"]["ndci_proxy"],
            turbidity_proxy_formula=context["indices"]["turbidity_proxy"],
            nodata_semantics="transparent; non-water pixel / no valid Sentinel-2 observation",
        )

    # --- 3 visualisation layers: colour (pct spread) → blur → mask → save ---
    generate_water_health_three_layer(output_values, sharp_path, glow_path, halo_path, study_mask, pct)

    wh_min   = float(valid_values.min())   if len(valid_values) else 0.0
    wh_max   = float(valid_values.max())   if len(valid_values) else 0.0
    wh_mean  = float(valid_values.mean())  if len(valid_values) else 0.0
    wh_med   = float(np.median(valid_values)) if len(valid_values) else 0.0
    p05 = float(pct.get("p05_raw", 0.0))
    p25 = float(pct.get("p25_raw", 0.0))
    p50 = float(pct.get("p50_raw", wh_med))
    p75 = float(pct.get("p75_raw", 0.0))
    p95 = float(pct.get("p95_raw", 0.0))
    west, south, east, north = (float(value) for value in bounds)

    geotiff_rel = str(geotiff_path.relative_to(output_root)).replace("\\", "/")
    sharp_rel   = str(sharp_path.relative_to(output_root)).replace("\\", "/")
    glow_rel    = str(glow_path.relative_to(output_root)).replace("\\", "/")
    halo_rel    = str(halo_path.relative_to(output_root)).replace("\\", "/")

    record: dict[str, Any] = {
        "metric": "water_health", "generation_status": "generated",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_timestamp": timestamp.isoformat(),
        "timestamp": stamp,
        "source_period": {"start": start_date, "end": end_date, "days": context.get("window_days", COMPOSITE_WINDOW_DAYS)},
        "source": "Google Earth Engine / Sentinel-2", "dataset": S2_DATASET,
        "methodology": METHODOLOGY,
        "interpretation": "Water body condition index 0..1; higher means healthier (less algal stress + less suspended-material stress averaged), computed only for pixels detected as water via MNDWI >= 0. Visualisation uses percentile-based colour spread so that tightly-clustered values show distinct saturated heatmap colours; scientific pixel values in the GeoTIFF are unchanged.",
        "semantic_label": "Water Health · Aquatic Condition Index",
        "preprocessing": {"composite": context["composite"], "window_days": context["window_days"],
                          "cloud_mask": context["cloud_mask"],
                          "mndwi_threshold": context["mndwi_threshold"],
                          "mndwi_formula": context["indices"]["mndwi"],
                          "ndci_proxy_formula": context["indices"]["ndci_proxy"],
                          "turbidity_proxy_formula": context["indices"]["turbidity_proxy"]},
        "images_found": image_count, "image_count": image_count, "crs": CRS,
        "scale_m": SCALE_METERS,
        "unit": "index_0_to_1",
        "bounds": {"west": west, "south": south, "east": east, "north": north},
        "mapbox_coordinates": mapbox_coordinates((west, south, east, north)),
        "coordinates": mapbox_coordinates((west, south, east, north)),
        "width": width, "height": height, "pixel_size_degrees": {"longitude": (east - west) / width, "latitude": (north - south) / height},
        "source_scale_m": SCALE_METERS, "nodata_value": NODATA_VALUE, "nodata": True,
        "nodata_semantics": "transparent; non-water pixel / no valid Sentinel-2 observation; study region clipped to Mumbai + Thane + Mira-Bhayandar boundaries (visualisation layers only)",
        "valid_pixels": int(valid.sum()), "nodata_pixels": int((~valid).sum()),
        "valid_pixel_percent": round(float(valid.mean() * 100), 3),
        "wh_min": round(wh_min, 3),
        "wh_max": round(wh_max, 3),
        "wh_mean": round(wh_mean, 3),
        "wh_median": round(wh_med, 3),
        "water_health_statistics": {
            "min": wh_min, "max": wh_max, "mean": wh_mean, "median": wh_med,
            "p05": p05, "p25": p25, "p50": p50, "p75": p75, "p95": p95,
        },
        "display_percentiles": {
            "p05_raw": p05, "p25_raw": p25, "p50_raw": p50, "p75_raw": p75, "p95_raw": p95,
            "raw_min": float(pct.get("raw_min", wh_min)),
            "raw_max": float(pct.get("raw_max", wh_max)),
        },
        "visualization": {
            "stops": [
                {"value": 0.00, "label": "degraded", "rgb": [221, 38, 154],  "raw_bound": p05, "quantile": "p05"},
                {"value": 0.18, "label": "poor",     "rgb": [255, 59, 59],   "raw_bound": None, "quantile": None},
                {"value": 0.38, "label": "fair",     "rgb": [255, 140, 0],   "raw_bound": p25, "quantile": "p25"},
                {"value": 0.58, "label": "good",     "rgb": [255, 210, 60],  "raw_bound": p50, "quantile": "p50"},
                {"value": 0.78, "label": "very good","rgb": [92, 214, 72],   "raw_bound": p75, "quantile": "p75"},
                {"value": 1.00, "label": "healthy",  "rgb": [18, 200, 212],  "raw_bound": p95, "quantile": "p95"},
            ],
            "legend": {
                "left_label": "DEGRADED",
                "right_label": "HEALTHY",
                "gradient": "magenta → red → orange → yellow → lime → teal/cyan",
            },
            "study_region_clipped": study_mask is not None,
            "percentile_normalized": True,
            "layers": ["halo", "glow", "sharp"],
        },
        "geotiff_filename": geotiff_rel,
        "png_filename": sharp_rel,
        "sharp_png_filename": sharp_rel,
        "glow_png_filename": glow_rel,
        "halo_png_filename": halo_rel,
        "files": {
            "geotiff": geotiff_path.name,
            "png": sharp_path.name,
            "sharp_png": sharp_path.name,
            "glow_png": glow_path.name,
            "halo_png": halo_path.name,
        },
        "checksums": {
            "geotiff_sha256": _sha256(geotiff_path),
            "png_sha256": _sha256(sharp_path),
            "sharp_png_sha256": _sha256(sharp_path),
            "glow_png_sha256": _sha256(glow_path),
            "halo_png_sha256": _sha256(halo_path),
        },
    }
    _write_manifest(record, output_root / "manifest.json")
    return record


def generate_water_health_surface(*, start_date: str, end_date: str) -> dict[str, Any]:
    """Generate a real current-window Water Health surface; no database writes occur."""
    initialize_ee()
    bounds = get_water_health_export_bounds()
    image, region, image_count = build_water_health_composite(start_date=start_date, end_date=end_date, bounds=bounds)
    with tempfile.TemporaryDirectory(prefix="geosense-wh-") as temp:
        downloaded = Path(temp) / "wh_download.tif"
        _download_geotiff(image, region, downloaded)
        return publish_water_health_geotiff(downloaded, start_date=start_date, end_date=end_date, image_count=image_count)


def load_latest_water_health_surface(manifest_path: Path = MANIFEST_PATH) -> dict[str, Any] | None:
    if not manifest_path.exists():
        return None
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    record = data.get("surfaces", {}).get("water_health")
    return record if isinstance(record, dict) and record.get("generation_status") == "generated" else None
