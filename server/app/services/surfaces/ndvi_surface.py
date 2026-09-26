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
METHODOLOGY = "Sentinel-2 median composite NDVI"
SERVER_ROOT = Path(__file__).resolve().parents[3]
SURFACE_ROOT = SERVER_ROOT / "data" / "surfaces"
MANIFEST_PATH = SURFACE_ROOT / "manifest.json"


def mapbox_coordinates(bounds: tuple[float, float, float, float]) -> list[list[float]]:
    west, south, east, north = bounds
    return [[west, north], [east, north], [east, south], [west, south]]


def get_study_region_mask(width: int, height: int, transform,
                           bounds: tuple[float, float, float, float]) -> np.ndarray | None:
    """Build a uint8 alpha mask (255=inside study region, 0=outside).

    Union of Mumbai + Thane + Mira-Bhayandar local GeoJSON boundaries.
    Rasterised to the same (width, height, transform) as the target raster so
    it can be applied pixel-for-pixel to the visualised RGBA layers.
    Returns None if the local boundary assets are unavailable so the caller
    can fall back to the existing behaviour instead of failing a surface build.
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
            # Clip to raster bounds defensively
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
    """Multiply alpha channel of an HxWx4 RGBA array by the study region mask.

    If mask is None, return the image unchanged (backward-compatible).
    """
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
    current.setdefault("surfaces", {})["ndvi"] = record
    temporary = manifest_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(manifest_path)


def get_ndvi_export_bounds() -> tuple[float, float, float, float]:
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
    """RGBA for one valid NDVI pixel — vibrant multi-color heatmap (visualization only).

    Scientific GeoTIFF values are unchanged; this only controls display colouring.

    Alpha ramp:
    - NDVI < 0.05 (water, deep urban concrete, bare rock) → fully transparent,
      so the dark Mapbox basemap shows through cleanly and no rectangular footprint.
    - 0.05 → 0.30: fade in (t^1.4) so sparse vegetation stays subtle until ~0.15.
    - ≥ 0.30: plateau at alpha 215.

    Colour progression (visualization only, does not change pixel values):
      0.05  → deep red / magenta   (very low)
      0.10  → orange               (low)
      0.20  → yellow               (moderate)
      0.35  → lime                 (moderate-high)
      0.55  → green                (high)
      0.80  → emerald / teal       (very high)
    """
    ALPHA_ZERO_BELOW = np.float32(0.05)
    ALPHA_FULL_ABOVE = np.float32(0.30)
    ALPHA_PLATEAU    = np.uint8(215)

    if not np.isfinite(value) or value == NODATA_VALUE:
        return (0, 0, 0, 0)
    if value < ALPHA_ZERO_BELOW:
        return (0, 0, 0, 0)
    if value < ALPHA_FULL_ABOVE:
        t = (value - ALPHA_ZERO_BELOW) / (ALPHA_FULL_ABOVE - ALPHA_ZERO_BELOW)
        alpha = int(round((t ** 1.4) * ALPHA_PLATEAU))
    else:
        alpha = int(ALPHA_PLATEAU)

    colour_stops: tuple[tuple[float, tuple[int, int, int]], ...] = (
        ( 0.05, (214,  39, 129)),
        ( 0.10, (255,  94,  40)),
        ( 0.20, (255, 205,  50)),
        ( 0.35, (168, 230,  53)),
        ( 0.55, ( 41, 217, 103)),
        ( 0.80, ( 20, 200, 180)),
    )
    lo_val, lo_rgb = colour_stops[0]
    hi_val, hi_rgb = colour_stops[-1]
    clamped = max(lo_val, min(hi_val, value))
    r, g, b = lo_rgb
    for (left, c0), (right, c1) in zip(colour_stops, colour_stops[1:]):
        if clamped <= right:
            t_seg = (clamped - left) / (right - left) if right > left else 0.0
            r = int(round(c0[0] + (c1[0] - c0[0]) * t_seg))
            g = int(round(c0[1] + (c1[1] - c0[1]) * t_seg))
            b = int(round(c0[2] + (c1[2] - c0[2]) * t_seg))
            break
    return (r, g, b, alpha)


def ndvi_to_rgba(values: np.ndarray) -> np.ndarray:
    """Vectorised NDVI → vibrant multi-colour heatmap RGBA (visualization only).

    Scientific pixel values in the GeoTIFF remain untouched; this function
    only controls the display raster that is shipped to Mapbox.
    """
    STOP_V = np.array([ 0.05,  0.10,  0.20,  0.35,  0.55,  0.80], dtype=np.float32)
    STOP_R = np.array([  214,   255,   255,   168,    41,    20  ], dtype=np.float32)
    STOP_G = np.array([   39,    94,   205,   230,   217,   200  ], dtype=np.float32)
    STOP_B = np.array([  129,    40,    50,    53,   103,   180  ], dtype=np.float32)
    ALPHA_ZERO = np.float32(0.05)
    ALPHA_FULL = np.float32(0.30)
    ALPHA_MAX  = np.float32(215.0)

    valid   = np.isfinite(values) & (values != NODATA_VALUE)
    clamped = np.where(valid, np.clip(values, STOP_V[0], STOP_V[-1]), STOP_V[0]).ravel()
    h, w = values.shape

    r_acc = np.zeros(h * w, np.float32)
    g_acc = np.zeros(h * w, np.float32)
    b_acc = np.zeros(h * w, np.float32)
    for i in range(len(STOP_V) - 1):
        lo, hi = STOP_V[i], STOP_V[i + 1]
        seg = (clamped >= lo) & (clamped <= hi)
        t_seg = np.where(seg, (clamped - lo) / (hi - lo), 0.0)
        r_acc += seg * (STOP_R[i] + (STOP_R[i + 1] - STOP_R[i]) * t_seg)
        g_acc += seg * (STOP_G[i] + (STOP_G[i + 1] - STOP_G[i]) * t_seg)
        b_acc += seg * (STOP_B[i] + (STOP_B[i + 1] - STOP_B[i]) * t_seg)

    v_flat = values.ravel()
    alpha_f = np.where(
        v_flat < ALPHA_ZERO, 0.0,
        np.where(
            v_flat < ALPHA_FULL,
            (((v_flat - ALPHA_ZERO) / (ALPHA_FULL - ALPHA_ZERO)).clip(0.0, 1.0) ** 1.4) * ALPHA_MAX,
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
    """Gaussian-blur an HxWx4 RGBA array using PIL, preserving alpha shape."""
    img = Image.fromarray(rgba, mode="RGBA")
    r, g, b, a = img.split()
    r2 = r.filter(ImageFilter.GaussianBlur(radius=radius))
    g2 = g.filter(ImageFilter.GaussianBlur(radius=radius))
    b2 = b.filter(ImageFilter.GaussianBlur(radius=radius))
    a2 = a.filter(ImageFilter.GaussianBlur(radius=radius))
    return np.array(Image.merge("RGBA", (r2, g2, b2, a2))).astype(np.uint8)


def generate_ndvi_three_layer(
    values: np.ndarray,
    sharp_path: Path,
    glow_path: Path,
    halo_path: Path,
    study_mask: np.ndarray | None,
) -> None:
    """Generate three NDVI visualization layers and write them as PNG.

    PROCESSING ORDER (to avoid halo bleeding outside the municipality boundary):
        1. scientific values → vibrant RGBA colouring
        2. blur → glow / halo
        3. apply study-region mask (multiplies alpha)
        4. save final PNG

    Parameters
    ----------
    values : 2D float32 array with NODATA_VALUE for NoData.
    study_mask : HxW uint8 or None — 255 inside Mumbai+Thane+Mira-Bhayandar, else 0.
    """
    sharp_rgba = ndvi_to_rgba(values)

    glow_rgba = _blur_rgba(sharp_rgba, radius=2.5)
    halo_rgba = _blur_rgba(sharp_rgba, radius=7.0)

    # Boost halo brightness slightly so it reads as a wide soft glow
    halo_rgba = halo_rgba.copy()
    halo_rgba[:, :, 3] = np.clip(halo_rgba[:, :, 3].astype(np.uint16) * 210 // 255, 0, 255).astype(np.uint8)

    # --- 3. Apply study-region mask LAST so blur cannot bleed outside boundary ---
    sharp_rgba = apply_study_region_mask(sharp_rgba, study_mask)
    glow_rgba  = apply_study_region_mask(glow_rgba,  study_mask)
    halo_rgba  = apply_study_region_mask(halo_rgba,  study_mask)

    Image.fromarray(sharp_rgba, mode="RGBA").save(sharp_path, "PNG", compress_level=6)
    Image.fromarray(glow_rgba,  mode="RGBA").save(glow_path,  "PNG", compress_level=6)
    Image.fromarray(halo_rgba,  mode="RGBA").save(halo_path,  "PNG", compress_level=6)


def publish_ndvi_geotiff(
    source_path: Path,
    *,
    start_date: str,
    end_date: str,
    image_count: int,
    output_root: Path = SURFACE_ROOT,
) -> dict[str, Any]:
    """Validate a real GEE export and publish canonical TIFF + 3 heatmap PNG layers.

    Visualisation layers:
        HALO  (wide soft glow, r=7)
        GLOW  (medium blur, r=2.5)
        SHARP (pixel-exact coloured raster)

    All three layers are clipped/masked to the study-region union (Mumbai +
    Thane + Mira-Bhayandar) AFTER blurring, so the glow/halo cannot bleed
    outside the municipal boundaries. Scientific GeoTIFF values are unchanged.
    """
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
        if np.any(values[valid] < -1.0) or np.any(values[valid] > 1.0):
            raise ValueError("NDVI export contains values outside the valid normalized-difference range")
        if not valid.any():
            raise ValueError("NDVI export has zero valid satellite pixels")
        output_values = np.where(valid, values, NODATA_VALUE).astype(np.float32)
        bounds = (source.bounds.left, source.bounds.bottom, source.bounds.right, source.bounds.top)
        transform = source.transform
        width, height = source.width, source.height

    # --- Study-region mask: rasterize union of MMB boundaries to this grid ---
    study_mask = get_study_region_mask(width, height, transform, bounds)

    output_dir = output_root / "ndvi"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
    stamp = timestamp.strftime("%Y%m%dT%H%M%SZ")
    geotiff_path = output_dir / f"ndvi_{stamp}.tif"
    sharp_path = output_dir / f"ndvi_{stamp}.png"
    glow_path  = output_dir / f"ndvi_{stamp}_glow.png"
    halo_path  = output_dir / f"ndvi_{stamp}_halo.png"

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

    # --- 3 visualisation layers: colour → blur → mask → save ---
    generate_ndvi_three_layer(output_values, sharp_path, glow_path, halo_path, study_mask)

    valid_values = output_values[output_values != NODATA_VALUE]
    west, south, east, north = (float(value) for value in bounds)
    ndvi_min = float(valid_values.min()) if len(valid_values) else 0.0
    ndvi_max = float(valid_values.max()) if len(valid_values) else 0.0
    ndvi_mean = float(valid_values.mean()) if len(valid_values) else 0.0
    ndvi_median = float(np.median(valid_values)) if len(valid_values) else 0.0
    p5  = float(np.percentile(valid_values, 5))  if len(valid_values) else 0.0
    p25 = float(np.percentile(valid_values, 25)) if len(valid_values) else 0.0
    p75 = float(np.percentile(valid_values, 75)) if len(valid_values) else 0.0
    p95 = float(np.percentile(valid_values, 95)) if len(valid_values) else 0.0

    geotiff_rel = str(geotiff_path.relative_to(output_root)).replace("\\", "/")
    sharp_rel   = str(sharp_path.relative_to(output_root)).replace("\\", "/")
    glow_rel    = str(glow_path.relative_to(output_root)).replace("\\", "/")
    halo_rel    = str(halo_path.relative_to(output_root)).replace("\\", "/")

    record: dict[str, Any] = {
        "metric": "ndvi", "generation_status": "generated",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_timestamp": timestamp.isoformat(),
        "timestamp": stamp,
        "source_period": {"start": start_date, "end": end_date},
        "source": "Google Earth Engine / Sentinel-2", "dataset": S2_DATASET,
        "methodology": METHODOLOGY,
        "interpretation": "NDVI · Vegetation Signal — satellite-derived normalised difference vegetation index; higher NDVI indicates a stronger green-vegetation signal. Visualisation only uses multi-colour heatmap display; scientific pixel values in the GeoTIFF are unchanged.",
        "semantic_label": "NDVI · Vegetation Signal",
        "preprocessing": {"composite": context["composite"], "window_days": context["window_days"],
                          "cloud_mask": context["cloud_mask"], "ndvi_formula": context["indices"]["ndvi"]},
        "images_found": image_count, "image_count": image_count, "crs": CRS,
        "scale_m": SCALE_METERS,
        "bounds": {"west": west, "south": south, "east": east, "north": north},
        "mapbox_coordinates": mapbox_coordinates((west, south, east, north)),
        "coordinates": mapbox_coordinates((west, south, east, north)),
        "width": width, "height": height, "pixel_size_degrees": {"longitude": (east - west) / width, "latitude": (north - south) / height},
        "source_scale_m": SCALE_METERS, "nodata_value": NODATA_VALUE, "nodata": True,
        "nodata_semantics": "transparent; no valid cloud-masked satellite NDVI pixel; study region clipped to Mumbai + Thane + Mira-Bhayandar boundaries (visualisation layers only)",
        "valid_pixels": int(valid.sum()), "nodata_pixels": int((~valid).sum()),
        "valid_pixel_percent": round(float(valid.mean() * 100), 3),
        "ndvi_statistics": {
            "min": ndvi_min, "max": ndvi_max, "mean": ndvi_mean, "median": ndvi_median,
            "p05": p5, "p25": p25, "p50": ndvi_median, "p75": p75, "p95": p95,
        },
        "visualization": {
            "stops": [
                {"value": 0.05, "label": "very low",  "rgb": [214, 39, 129]},
                {"value": 0.10, "label": "low",       "rgb": [255, 94, 40]},
                {"value": 0.20, "label": "moderate",  "rgb": [255, 205, 50]},
                {"value": 0.35, "label": "moderate-high", "rgb": [168, 230, 53]},
                {"value": 0.55, "label": "high",      "rgb": [41, 217, 103]},
                {"value": 0.80, "label": "very high", "rgb": [20, 200, 180]},
            ],
            "legend": {
                "left_label": "LOW",
                "right_label": "HIGH",
                "gradient": "red → orange → yellow → lime → green → teal",
            },
            "study_region_clipped": study_mask is not None,
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
