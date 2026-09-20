"""Static Sentinel-2 NDVI surface artifacts for Mapbox.

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
from PIL import Image

_RASTERIO_PROJ_DATA = Path(sys.prefix) / "Lib" / "site-packages" / "rasterio" / "proj_data"
if _RASTERIO_PROJ_DATA.is_dir():
    os.environ["PROJ_LIB"] = str(_RASTERIO_PROJ_DATA)
    os.environ["PROJ_DATA"] = str(_RASTERIO_PROJ_DATA)
import rasterio
from sqlalchemy import text
import requests

from app.database import engine
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
METHODOLOGY = "Sentinel-2 median composite NDVI"
SERVER_ROOT = Path(__file__).resolve().parents[3]
SURFACE_ROOT = SERVER_ROOT / "data" / "surfaces"
MANIFEST_PATH = SURFACE_ROOT / "manifest.json"


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
    current.setdefault("surfaces", {})["ndvi"] = record
    temporary = manifest_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(manifest_path)


def get_ndvi_export_bounds() -> tuple[float, float, float, float]:
    """Read the established GeoSense analysis extent without changing zones."""
    statement = text("""
        SELECT ST_XMin(extent) AS west, ST_YMin(extent) AS south,
               ST_XMax(extent) AS east, ST_YMax(extent) AS north
        FROM (SELECT ST_Extent(geometry)::box3d AS extent FROM zones) zone_extent
    """)
    with engine.connect() as connection:
        row = connection.execute(statement).mappings().one()
    bounds = tuple(float(row[key]) for key in ("west", "south", "east", "north"))
    if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
        raise ValueError("GeoSense analysis extent is invalid")
    return bounds


def build_ndvi_composite(*, start_date: str, end_date: str, bounds: tuple[float, float, float, float]):
    """Build exactly the established cloud-masked Sentinel-2 NDVI composite."""
    source_context(start_date, end_date)  # fixed 14-day compatibility guard
    region = ee.Geometry.Rectangle(list(bounds), proj=CRS, geodesic=False)
    collection = (
        ee.ImageCollection(S2_DATASET)
        .filterDate(start_date, end_date)
        .filterBounds(region)
        .map(mask_s2_sr)
        .map(add_indices)
    )
    image_count = int(collection.size().getInfo())
    if image_count == 0:
        raise ValueError("No Sentinel-2 images found for the configured NDVI composite window")
    return collection.median().select("NDVI").clip(region), region, image_count


def _download_geotiff(image: Any, region: Any, destination: Path) -> None:
    url = image.getDownloadURL({
        "scale": SCALE_METERS,
        "crs": CRS,
        "region": region,
        "format": "GEO_TIFF",
        "filePerBand": False,
    })
    response = requests.get(url, timeout=240)
    response.raise_for_status()
    destination.write_bytes(response.content)
    # Earth Engine can return a zipped TIFF depending on service behaviour.
    if zipfile.is_zipfile(destination):
        with zipfile.ZipFile(destination) as archive:
            tiffs = [member for member in archive.namelist() if member.lower().endswith((".tif", ".tiff"))]
            if len(tiffs) != 1:
                raise ValueError("Earth Engine download did not contain exactly one NDVI GeoTIFF")
            extracted = destination.parent / Path(tiffs[0]).name
            with archive.open(tiffs[0]) as source, extracted.open("wb") as target:
                shutil.copyfileobj(source, target)
        destination.unlink()
        extracted.replace(destination)


def _ndvi_rgba(value: float) -> tuple[int, int, int, int]:
    """RGBA for one valid NDVI pixel.

    Design goals (visualization only — scientific GeoTIFF is unchanged):
    - Water / negative NDVI (< 0.05): fully transparent.
      Urban hard surfaces, roads, buildings are typically NDVI 0.0-0.15 —
      keep those transparent so the dark basemap shows through cleanly and
      the raster does not look like a brown rectangle pasted over the city.
    - Sparse / stressed vegetation (0.05 – 0.20): rapidly fading from 0 to
      partial alpha. Low-vegetation pixels fade in quickly but remain subtle.
    - Moderate vegetation (0.20 – 0.40): semi-opaque warm green signal.
    - Healthy vegetation (0.40 – 0.65): clearly visible saturated green.
    - Dense / peak vegetation (0.65+): vivid opaque green.

    The key change from the previous ramp: transparency is pushed much deeper
    (zero below 0.05, plateau not reached until 0.35) so that the dominant
    urban fabric of Mumbai stays dark/basemap rather than olive-brown.
    """
    # ── Alpha ramp ────────────────────────────────────────────────────────────
    ALPHA_ZERO_BELOW = 0.05    # fully transparent — water, deep urban, bare rock
    ALPHA_FULL_ABOVE = 0.35    # full alpha reached here — solid vegetation signal
    ALPHA_PLATEAU    = 210     # max alpha (not 255 — preserves basemap context)

    if value < ALPHA_ZERO_BELOW:
        alpha = 0
    elif value < ALPHA_FULL_ABOVE:
        t = (value - ALPHA_ZERO_BELOW) / (ALPHA_FULL_ABOVE - ALPHA_ZERO_BELOW)
        # Use a mild power curve so sparse vegetation (0.05-0.15) stays very
        # faint and the signal only becomes visible above 0.20.
        alpha = round((t ** 1.6) * ALPHA_PLATEAU)
    else:
        alpha = ALPHA_PLATEAU

    # ── RGB colour ramp ───────────────────────────────────────────────────────
    # Scientific green ramp — reads as vegetation index, not satellite photo.
    # Values below the alpha threshold are invisible so their colour is moot.
    colour_stops: tuple[tuple[float, tuple[int, int, int]], ...] = (
        ( 0.00, ( 40,  48,  30)),  # deep olive-dark — bare/sparse
        ( 0.10, ( 58,  72,  28)),  # dark olive-green — very sparse
        ( 0.20, ( 72, 100,  32)),  # olive-green — sparse shrub
        ( 0.30, ( 65, 130,  35)),  # muted green — open scrub
        ( 0.42, ( 48, 158,  42)),  # natural green — moderate canopy
        ( 0.55, ( 30, 175,  50)),  # bright green — healthy vegetation
        ( 0.68, ( 16, 190,  58)),  # vivid green — dense canopy
        ( 0.80, (  5, 205,  65)),  # peak green — maximum vegetation signal
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


def ndvi_to_rgba(values: np.ndarray) -> np.ndarray:
    """Convert float32 NDVI grid to RGBA uint8 image — fully vectorised.

    Colour stops and alpha ramp match _ndvi_rgba().
    NoData (-9999) and non-finite → alpha 0 (fully transparent).
    """
    STOP_V = np.array([ 0.00,  0.10,  0.20,  0.30,  0.42,  0.55,  0.68,  0.80], dtype=np.float32)
    STOP_R = np.array([ 40,    58,    72,    65,    48,    30,    16,     5  ], dtype=np.float32)
    STOP_G = np.array([ 48,    72,   100,   130,   158,   175,   190,   205  ], dtype=np.float32)
    STOP_B = np.array([ 30,    28,    32,    35,    42,    50,    58,    65  ], dtype=np.float32)
    ALPHA_ZERO = np.float32( 0.05)
    ALPHA_FULL = np.float32( 0.35)
    ALPHA_MAX  = np.float32( 210.0)

    valid   = np.isfinite(values) & (values != NODATA_VALUE)
    clamped = np.where(valid, np.clip(values, STOP_V[0], STOP_V[-1]),
                       STOP_V[0]).ravel()
    h, w = values.shape

    r_acc = np.zeros(h * w, np.float32)
    g_acc = np.zeros(h * w, np.float32)
    b_acc = np.zeros(h * w, np.float32)

    for i in range(len(STOP_V) - 1):
        lo, hi = STOP_V[i], STOP_V[i + 1]
        seg = (clamped >= lo) & (clamped <= hi)
        t   = np.where(seg, (clamped - lo) / (hi - lo), 0.0)
        r_acc += seg * (STOP_R[i] + (STOP_R[i + 1] - STOP_R[i]) * t)
        g_acc += seg * (STOP_G[i] + (STOP_G[i + 1] - STOP_G[i]) * t)
        b_acc += seg * (STOP_B[i] + (STOP_B[i + 1] - STOP_B[i]) * t)

    v_flat = values.ravel()
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


def publish_ndvi_geotiff(
    source_path: Path,
    *,
    start_date: str,
    end_date: str,
    image_count: int,
    output_root: Path = SURFACE_ROOT,
) -> dict[str, Any]:
    """Validate a real GEE export and publish canonical TIFF, PNG and manifest."""
    context = source_context(start_date, end_date)
    with rasterio.open(source_path) as source:
        if source.count != 1:
            raise ValueError("NDVI export must contain exactly one raster band")
        if source.crs is None or source.crs.to_string() != CRS:
            raise ValueError(f"NDVI export must use {CRS}; received {source.crs}")
        values = source.read(1).astype(np.float32)
        mask = source.read_masks(1) > 0
        nodata = source.nodata
        if nodata is not None:
            mask &= values != nodata
        valid = mask & np.isfinite(values)
        # Valid normalized differences must remain physically bounded.
        if np.any(values[valid] < -1.0) or np.any(values[valid] > 1.0):
            raise ValueError("NDVI export contains values outside the valid normalized-difference range")
        if not valid.any():
            raise ValueError("NDVI export has zero valid satellite pixels")
        output_values = np.where(valid, values, NODATA_VALUE).astype(np.float32)
        bounds = (source.bounds.left, source.bounds.bottom, source.bounds.right, source.bounds.top)
        transform = source.transform
        width, height = source.width, source.height

    output_dir = output_root / "ndvi"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
    stamp = timestamp.strftime("%Y%m%dT%H%M%SZ")
    geotiff_path = output_dir / f"ndvi_{stamp}.tif"
    png_path = output_dir / f"ndvi_{stamp}.png"
    with rasterio.open(
        geotiff_path, "w", driver="GTiff", height=height, width=width, count=1,
        dtype="float32", crs=CRS, transform=transform, nodata=NODATA_VALUE, compress="deflate",
    ) as output:
        output.write(output_values, 1)
        output.update_tags(
            metric="ndvi", source="Google Earth Engine / Sentinel-2",
            dataset=S2_DATASET, methodology=METHODOLOGY,
            window_start=start_date, window_end=end_date,
            cloud_mask=context["cloud_mask"], ndvi_formula=context["indices"]["ndvi"],
            nodata_semantics="No valid cloud-masked satellite NDVI pixel; not low vegetation",
        )
    Image.fromarray(ndvi_to_rgba(output_values), mode="RGBA").save(png_path)

    valid_values = output_values[output_values != NODATA_VALUE]
    west, south, east, north = (float(value) for value in bounds)
    record: dict[str, Any] = {
        "metric": "ndvi", "generation_status": "generated",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_timestamp": timestamp.isoformat(),
        "source_period": {"start": start_date, "end": end_date},
        "source": "Google Earth Engine / Sentinel-2", "dataset": S2_DATASET,
        "methodology": METHODOLOGY,
        "interpretation": "Satellite-derived vegetation index; higher NDVI generally indicates a stronger green-vegetation signal.",
        "preprocessing": {"composite": context["composite"], "window_days": context["window_days"],
                          "cloud_mask": context["cloud_mask"], "ndvi_formula": context["indices"]["ndvi"]},
        "images_found": image_count, "crs": CRS,
        "bounds": {"west": west, "south": south, "east": east, "north": north},
        "mapbox_coordinates": mapbox_coordinates((west, south, east, north)),
        "width": width, "height": height, "pixel_size_degrees": {"longitude": (east - west) / width, "latitude": (north - south) / height},
        "source_scale_m": SCALE_METERS, "nodata_value": NODATA_VALUE,
        "nodata_semantics": "transparent; no valid cloud-masked satellite NDVI pixel",
        "valid_pixels": int(valid.sum()), "nodata_pixels": int((~valid).sum()),
        "valid_pixel_percent": round(float(valid.mean() * 100), 3),
        "ndvi_statistics": {"min": float(valid_values.min()), "max": float(valid_values.max()), "mean": float(valid_values.mean())},
        "geotiff_filename": str(geotiff_path.relative_to(output_root)).replace("\\", "/"),
        "png_filename": str(png_path.relative_to(output_root)).replace("\\", "/"),
        "checksums": {"geotiff_sha256": _sha256(geotiff_path), "png_sha256": _sha256(png_path)},
    }
    _write_manifest(record, output_root / "manifest.json")
    return record


def generate_ndvi_surface(*, start_date: str, end_date: str) -> dict[str, Any]:
    """Generate a real current-window NDVI surface; no database writes occur."""
    initialize_ee()
    bounds = get_ndvi_export_bounds()
    image, region, image_count = build_ndvi_composite(start_date=start_date, end_date=end_date, bounds=bounds)
    with tempfile.TemporaryDirectory(prefix="geosense-ndvi-") as temp:
        downloaded = Path(temp) / "ndvi_download.tif"
        _download_geotiff(image, region, downloaded)
        return publish_ndvi_geotiff(downloaded, start_date=start_date, end_date=end_date, image_count=image_count)


def load_latest_ndvi_surface(manifest_path: Path = MANIFEST_PATH) -> dict[str, Any] | None:
    # ═══════════════════════════════════════════════════════════════════════════
    # NDVI LOADER DIAGNOSTICS
    # ═══════════════════════════════════════════════════════════════════════════
    print(f"[NDVI LOADER] load_latest_ndvi_surface called")
    print(f"[NDVI LOADER] manifest_path: {manifest_path}")
    import sys
    sys.stdout.flush()
    # ═══════════════════════════════════════════════════════════════════════════
    
    if not manifest_path.exists():
        print(f"[NDVI LOADER] Manifest does not exist, returning None")
        sys.stdout.flush()
        return None
    
    print(f"[NDVI LOADER] Reading manifest file")
    sys.stdout.flush()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    print(f"[NDVI LOADER] Manifest loaded, checking for ndvi surface")
    sys.stdout.flush()
    
    record = data.get("surfaces", {}).get("ndvi")
    print(f"[NDVI LOADER] NDVI record found: {record is not None}")
    if record:
        print(f"[NDVI LOADER] generation_status: {record.get('generation_status')}")
    sys.stdout.flush()
    
    result = record if isinstance(record, dict) and record.get("generation_status") == "generated" else None
    print(f"[NDVI LOADER] Returning: {result is not None}")
    sys.stdout.flush()
    return result
