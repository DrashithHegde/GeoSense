"""Static Landsat 8/9 LST surface artifacts for Mapbox.

This module builds continuous land-surface temperature rasters suitable for
thermal-style visualization. It reuses the established Landsat C2 L2 preprocessing
from gee/ingest_lst.py and writes derived visualization files (GeoTIFF + PNG + glow).

The frozen zone geometry is used solely to obtain the existing study extent for
a rectangular satellite export. This does not read zone averages as pixels nor
write to the database.
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
from sqlalchemy import text
import requests

from app.database import engine
from gee.gee_client import initialize_ee
from gee.ingest_lst import (
    COMPOSITE_WINDOW_DAYS,
    LST_DATASETS,
    add_lst_celsius,
    mask_landsat_l2,
    source_context,
)

CRS = "EPSG:4326"
NODATA_VALUE = -9999.0
SCALE_METERS = 30
METHODOLOGY = "Landsat 8/9 Collection 2 Level-2 median composite LST"
SERVER_ROOT = Path(__file__).resolve().parents[3]
SURFACE_ROOT = SERVER_ROOT / "data" / "surfaces"
MANIFEST_PATH = SURFACE_ROOT / "manifest.json"
LST_GLOW_THRESHOLD_C = 35.0  # Named threshold for glow layer (hot surfaces)


def mapbox_coordinates(bounds: tuple[float, float, float, float]) -> list[list[float]]:
    west, south, east, north = bounds
    return [[west, north], [east, north], [east, south], [west, south]]


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
    current.setdefault("surfaces", {})["lst"] = record
    temporary = manifest_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(manifest_path)


def get_lst_export_bounds() -> tuple[float, float, float, float]:
    """Read the established GeoSense analysis extent and expand slightly to include
    natural areas like Sanjay Gandhi National Park (north of the urban zone extent).
    """
    statement = text("""
        SELECT ST_XMin(extent) AS west, ST_YMin(extent) AS south,
               ST_XMax(extent) AS east, ST_YMax(extent) AS north
        FROM (SELECT ST_Extent(geometry)::box3d AS extent FROM zones) zone_extent
    """)
    with engine.connect() as connection:
        row = connection.execute(statement).mappings().one()
    
    # Expand bounds to include Sanjay Gandhi National Park and surrounding natural areas
    west = float(row["west"]) - 0.08   # ~8km west expansion
    south = float(row["south"]) - 0.05  # ~5km south expansion
    east = float(row["east"]) + 0.03    # ~3km east expansion
    north = float(row["north"]) + 0.12  # ~12km north expansion (captures national park)
    
    if west >= east or south >= north:
        raise ValueError("GeoSense analysis extent is invalid")
    return (west, south, east, north)


def build_lst_composite(*, start_date: str, end_date: str, bounds: tuple[float, float, float, float]):
    """Build the established cloud-masked Landsat 8/9 LST composite."""
    source_context(start_date, end_date)  # fixed 45-day compatibility guard
    region = ee.Geometry.Rectangle(list(bounds), proj=CRS, geodesic=False)
    l8 = (
        ee.ImageCollection(LST_DATASETS[0])
        .filterDate(start_date, end_date)
        .filterBounds(region)
    )
    l9 = (
        ee.ImageCollection(LST_DATASETS[1])
        .filterDate(start_date, end_date)
        .filterBounds(region)
    )
    merged = l8.merge(l9)
    processed = merged.map(mask_landsat_l2).map(add_lst_celsius)
    return processed.median().select("LST")


def _lst_rgba(value: float) -> tuple[int, int, int, int]:
    """RGBA for one valid LST pixel.

    TRUE THERMAL / FLIR visualization: black background, hot objects glow intensely.
    This mimics actual thermal imaging cameras where heat = bright emission.

    Cool surfaces (water, vegetation) → near-black, almost invisible
    Moderate heat (buildings, roads) → deep purple glow
    Hot surfaces (exposed rooftops) → magenta-red glow
    Very hot surfaces (metal, direct sun) → orange-white intense glow
    """
    # ── Alpha ramp ────────────────────────────────────────────────────────────
    # Cool surfaces stay nearly transparent (FLIR shows minimal thermal signature).
    # Hot surfaces become increasingly opaque and bright.
    ALPHA_ZERO_BELOW = 20.0   # Below 20°C → transparent (water, cool vegetation)
    ALPHA_FULL_ABOVE = 35.0   # Above 35°C → full intensity (hot urban surfaces)
    ALPHA_PLATEAU = 235       # High alpha for bright hot-object glow

    if value < ALPHA_ZERO_BELOW:
        alpha = 0
    elif value < ALPHA_FULL_ABOVE:
        # Non-linear ramp: hot surfaces become visible much faster
        t = (value - ALPHA_ZERO_BELOW) / (ALPHA_FULL_ABOVE - ALPHA_ZERO_BELOW)
        alpha = round((t ** 1.3) * ALPHA_PLATEAU)
    else:
        alpha = ALPHA_PLATEAU

    # ── RGB FLIR / thermal ramp ──────────────────────────────────────────────────
    # TRUE thermal imaging: BLACK → DEEP PURPLE → MAGENTA → RED-HOT → ORANGE → WHITE
    # The hottest objects glow brightest (white-hot), coolest stay dark.
    colour_stops: tuple[tuple[float, tuple[int, int, int]], ...] = (
        (15.0, (  0,   0,   0)),  # pure black — no thermal signature
        (22.0, ( 18,   8,  28)),  # very deep purple — barely visible
        (26.0, ( 48,  18,  68)),  # deep purple — cool surfaces
        (29.0, ( 88,  28, 118)),  # purple — moderate heat
        (32.0, (138,  38, 128)),  # magenta-purple — warm surfaces
        (34.0, (188,  42, 108)),  # hot magenta — hot pavement
        (36.0, (228,  58,  78)),  # red-hot — very hot surfaces
        (38.0, (255,  98,  48)),  # orange-red — extreme heat
        (40.0, (255, 168,  88)),  # bright orange — metal in sun
        (43.0, (255, 235, 195)),  # near-white — white-hot extreme
    )
    lo_val, lo_rgb = colour_stops[0]
    hi_val, hi_rgb = colour_stops[-1]
    clamped = max(lo_val, min(hi_val, value))
    r, g, b = lo_rgb
    for (left, c0), (right, c1) in zip(colour_stops, colour_stops[1:]):
        if clamped <= right:
            t = (clamped - left) / (right - left) if right > left else 0.0
            r = round(c0[0] + (c1[0] - c0[0]) * t)
            g = round(c0[1] + (c1[1] - c0[1]) * t)
            b = round(c0[2] + (c1[2] - c0[2]) * t)
            break

    return (r, g, b, alpha)


def lst_to_rgba(values: np.ndarray) -> np.ndarray:
    """Convert float32 LST grid to RGBA uint8 image — fully vectorised.

    Colour stops and alpha ramp match _lst_rgba().
    NoData (-9999) and non-finite → alpha 0 (fully transparent).
    """
    STOP_V = np.array([15.0, 22.0, 26.0, 29.0, 32.0, 34.0, 36.0, 38.0, 40.0, 43.0], dtype=np.float32)
    STOP_R = np.array([  0,   18,   48,   88,  138,  188,  228,  255,  255,  255 ], dtype=np.float32)
    STOP_G = np.array([  0,    8,   18,   28,   38,   42,   58,   98,  168,  235 ], dtype=np.float32)
    STOP_B = np.array([  0,   28,   68,  118,  128,  108,   78,   48,   88,  195 ], dtype=np.float32)
    ALPHA_ZERO = np.float32(20.0)
    ALPHA_FULL = np.float32(35.0)
    ALPHA_MAX  = np.float32(235.0)

    valid = np.isfinite(values) & (values != NODATA_VALUE)
    clamped = np.where(valid, np.clip(values, STOP_V[0], STOP_V[-1]),
                       STOP_V[0]).ravel()
    h, w = values.shape

    r_acc = np.zeros(h * w, np.float32)
    g_acc = np.zeros(h * w, np.float32)
    b_acc = np.zeros(h * w, np.float32)

    for i in range(len(STOP_V) - 1):
        lo, hi = STOP_V[i], STOP_V[i + 1]
        seg = (clamped >= lo) & (clamped <= hi)
        t = np.where(seg, (clamped - lo) / (hi - lo), 0.0)
        r_acc += seg * (STOP_R[i] + (STOP_R[i + 1] - STOP_R[i]) * t)
        g_acc += seg * (STOP_G[i] + (STOP_G[i + 1] - STOP_G[i]) * t)
        b_acc += seg * (STOP_B[i] + (STOP_B[i + 1] - STOP_B[i]) * t)

    v_flat = values.ravel()
    alpha_f = np.where(
        v_flat < ALPHA_ZERO, 0.0,
        np.where(
            v_flat < ALPHA_FULL,
            (((v_flat - ALPHA_ZERO) / (ALPHA_FULL - ALPHA_ZERO)).clip(0.0, 1.0) ** 1.3) * ALPHA_MAX,
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


def generate_glow_png(values: np.ndarray, transform, crs, output_path: Path) -> None:
    """Generate a separate glow PNG for hot pixels (LST >= LST_GLOW_THRESHOLD_C).

    Process:
    1. Mask to hot pixels only
    2. Apply same thermal palette
    3. Gaussian blur for subtle glow
    4. Export as RGBA PNG
    """
    # Mask: only keep pixels above the glow threshold
    hot_mask = np.isfinite(values) & (values >= LST_GLOW_THRESHOLD_C)
    glow_values = np.where(hot_mask, values, np.nan)

    # Render RGBA with same thermal palette
    rgba = lst_to_rgba(np.nan_to_num(glow_values, nan=NODATA_VALUE))

    # Apply Gaussian blur to RGB channels only (preserve alpha structure)
    img = Image.fromarray(rgba, mode="RGBA")
    r, g, b, a = img.split()

    # Subtle blur — radius 3.0 gives a gentle glow without massive smearing
    r_blur = r.filter(ImageFilter.GaussianBlur(radius=3.0))
    g_blur = g.filter(ImageFilter.GaussianBlur(radius=3.0))
    b_blur = b.filter(ImageFilter.GaussianBlur(radius=3.0))

    # Recombine with original alpha (don't blur alpha — keeps edges clean)
    glow_img = Image.merge("RGBA", (r_blur, g_blur, b_blur, a))
    glow_img.save(output_path, "PNG", compress_level=6)


def publish_lst_geotiff(
    source_path: Path,
    *,
    start_date: str,
    end_date: str,
    image_count: int,
    output_root: Path = SURFACE_ROOT,
) -> dict[str, Any]:
    """Validate a real GEE export and publish canonical TIFF, PNG, glow PNG, and manifest."""
    context = source_context(start_date, end_date)
    with rasterio.open(source_path) as source:
        if source.count != 1:
            raise ValueError("LST export must contain exactly one raster band")
        if source.crs is None or source.crs.to_string() != CRS:
            raise ValueError(f"LST export must use {CRS}; got {source.crs}")

        values = source.read(1)
        transform = source.transform
        bounds = source.bounds
        profile = source.profile.copy()

    valid_mask = np.isfinite(values) & (values != NODATA_VALUE)
    valid_count = int(np.sum(valid_mask))
    if valid_count == 0:
        raise ValueError("LST export contains zero valid pixels")

    valid_values = values[valid_mask]
    lst_min = float(np.min(valid_values))
    lst_max = float(np.max(valid_values))
    lst_mean = float(np.mean(valid_values))
    lst_median = float(np.median(valid_values))

    timestamp_str = datetime.fromisoformat(end_date).strftime("%Y%m%dT%H%M%SZ")
    output_dir = output_root / "lst"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Canonical GeoTIFF
    canonical_tiff = output_dir / f"lst_{timestamp_str}.tif"
    with rasterio.open(canonical_tiff, "w", **profile) as dest:
        dest.write(values, 1)

    # Sharp visualization PNG
    rgba = lst_to_rgba(values)
    sharp_png = output_dir / f"lst_{timestamp_str}.png"
    Image.fromarray(rgba, mode="RGBA").save(sharp_png, "PNG", compress_level=6)

    # Glow PNG for hot pixels
    glow_png = output_dir / f"lst_{timestamp_str}_glow.png"
    generate_glow_png(values, transform, source.crs, glow_png)

    record = {
        "metric": "lst",
        "methodology": METHODOLOGY,
        "dataset": " + ".join(LST_DATASETS),
        "source_period": {"start": start_date, "end": end_date, "days": COMPOSITE_WINDOW_DAYS},
        "image_count": image_count,
        "scale_m": SCALE_METERS,
        "unit": "celsius",
        "bounds": {"west": bounds.left, "south": bounds.bottom, "east": bounds.right, "north": bounds.top},
        "coordinates": mapbox_coordinates((bounds.left, bounds.bottom, bounds.right, bounds.top)),
        "nodata": True,
        "nodata_value": NODATA_VALUE,
        "valid_pixels": valid_count,
        "lst_min_c": round(lst_min, 2),
        "lst_max_c": round(lst_max, 2),
        "lst_mean_c": round(lst_mean, 2),
        "lst_median_c": round(lst_median, 2),
        "glow_threshold_c": LST_GLOW_THRESHOLD_C,
        "timestamp": timestamp_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": {
            "geotiff": canonical_tiff.name,
            "png": sharp_png.name,
            "glow_png": glow_png.name,
        },
        "checksums": {
            "geotiff_sha256": _sha256(canonical_tiff),
            "png_sha256": _sha256(sharp_png),
            "glow_png_sha256": _sha256(glow_png),
        },
    }

    _write_manifest(record, MANIFEST_PATH)

    return record


def generate_lst_surface(start_date: str, end_date: str) -> dict[str, Any]:
    """End-to-end LST surface generation using established project architecture."""
    initialize_ee()
    bounds = get_lst_export_bounds()
    composite = build_lst_composite(start_date=start_date, end_date=end_date, bounds=bounds)

    # Request export via GEE
    region = ee.Geometry.Rectangle(list(bounds), proj=CRS, geodesic=False)
    task_config = {
        "image": composite,
        "description": f"GeoSense_LST_{end_date}",
        "fileFormat": "GeoTIFF",
        "region": region,
        "scale": SCALE_METERS,
        "crs": CRS,
        "maxPixels": 1e9,
    }

    # Export to Drive then download (established pattern)
    task = ee.batch.Export.image.toDrive(**task_config)
    task.start()

    print(f"Started GEE export task: {task.id}")
    print("Waiting for export to complete...")

    import time
    while task.active():
        time.sleep(10)
        print(f"  Task status: {task.status()['state']}")

    final_status = task.status()
    if final_status["state"] != "COMPLETED":
        raise RuntimeError(f"GEE export failed: {final_status}")

    print("Export completed. Download the GeoTIFF from Google Drive and place it in a temporary directory.")
    print("Then call publish_lst_geotiff() with the path to the downloaded file.")

    return {
        "task_id": task.id,
        "status": "export_completed_awaiting_download",
        "bounds": bounds,
        "start_date": start_date,
        "end_date": end_date,
    }


def load_latest_lst_surface() -> dict[str, Any] | None:
    """Load the latest LST surface metadata from manifest, or None if unavailable."""
    if not MANIFEST_PATH.exists():
        return None
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        return manifest.get("surfaces", {}).get("lst")
    except (OSError, json.JSONDecodeError):
        return None
