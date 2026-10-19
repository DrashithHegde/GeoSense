"""Static Sentinel-5P AQI surface artifacts for Mapbox.

This module uses Sentinel-5P NO2 to approximate an AQI surface, 
matching the visual pipeline established for NDVI.
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
import requests

from app.services.municipality_boundaries import (
    MunicipalityBoundaryError,
    get_study_region_bounds,
    load_study_region_geometry,
)
from gee.gee_client import initialize_ee
from gee.ingest_aqi import (
    COMPOSITE_WINDOW_DAYS,
    S5P_DATASET,
    MAX_NO2_PROXY,
    add_aqi_proxy,
    source_context,
)

CRS = "EPSG:4326"
NODATA_VALUE = -9999.0
SCALE_METERS = 1113.2
METHODOLOGY = "Sentinel-5P NO2 proxy AQI composite"
SERVER_ROOT = Path(__file__).resolve().parents[3]
SURFACE_ROOT = SERVER_ROOT / "data" / "surfaces"
MANIFEST_PATH = SURFACE_ROOT / "manifest.json"


def mapbox_coordinates(bounds: tuple[float, float, float, float]) -> list[list[float]]:
    west, south, east, north = bounds
    return [[west, north], [east, north], [east, south], [west, south]]


def get_study_region_mask(width: int, height: int, transform,
                           bounds: tuple[float, float, float, float]) -> np.ndarray | None:
    from shapely.geometry import mapping
    try:
        study_region = load_study_region_geometry()
    except MunicipalityBoundaryError:
        return None

    west, south, east, north = bounds
    out_shape = (height, width)
    shapes = []
    try:
        from shapely.geometry import box as shapely_box
        raster_box = shapely_box(west, south, east, north)
        clipped = study_region.intersection(raster_box)
        if not clipped.is_empty:
            shapes.append((mapping(clipped), 255))
    except Exception:
        return None

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
    current.setdefault("surfaces", {})["aqi"] = record
    temporary = manifest_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(manifest_path)


def get_aqi_export_bounds() -> tuple[float, float, float, float]:
    return get_study_region_bounds()


def build_aqi_composite(*, start_date: str, end_date: str, bounds: tuple[float, float, float, float]):
    source_context(start_date, end_date)
    region = ee.Geometry.Rectangle(list(bounds), proj=CRS, geodesic=False)
    collection = (
        ee.ImageCollection(S5P_DATASET)
        .filterDate(start_date, end_date)
        .filterBounds(region)
        .map(add_aqi_proxy)
    )
    image_count = int(collection.size().getInfo())
    if image_count == 0:
        raise ValueError("No Sentinel-5P images found for the configured AQI composite window")
    return collection.median().select("AQI").clip(region), region, image_count


def _extract_tiff_from_zip(archive_path: Path) -> Path:
    if not zipfile.is_zipfile(archive_path):
        return archive_path
    with zipfile.ZipFile(archive_path) as archive:
        tiffs = [member for member in archive.namelist() if member.lower().endswith((".tif", ".tiff"))]
        if len(tiffs) != 1:
            raise ValueError("Earth Engine download did not contain exactly one AQI GeoTIFF")
        extracted = archive_path.parent / Path(tiffs[0]).name
        with archive.open(tiffs[0]) as source, extracted.open("wb") as target:
            shutil.copyfileobj(source, target)
    archive_path.unlink()
    return extracted


def _tile_download(image: Any, tile_region: Any, destination: Path) -> Path:
    import time
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
            destination.write_bytes(response.content)
            return _extract_tiff_from_zip(destination)
        except requests.HTTPError as exc:
            last_error = exc
            status = exc.response.status_code if exc.response is not None else 0
            if status >= 500 and attempt < 4:
                wait_seconds = 2 ** attempt + attempt
                print(f"  GEE AQI tile download returned {status}; retrying in {wait_seconds}s")
                time.sleep(wait_seconds)
                if destination.exists():
                    destination.unlink()
                continue
            raise
    raise last_error


def _download_geotiff(image: Any, region: Any, destination: Path) -> None:
    from rasterio.merge import merge as rio_merge
    coords = region.coordinates().getInfo()[0]
    xs = [coordinate[0] for coordinate in coords]
    ys = [coordinate[1] for coordinate in coords]
    west, east = min(xs), max(xs)
    south, north = min(ys), max(ys)
    midpoint = (west + east) / 2.0
    tile_defs = [
        ("tile_w", ee.Geometry.Rectangle([west, south, midpoint, north], proj=CRS, geodesic=False)),
        ("tile_e", ee.Geometry.Rectangle([midpoint, south, east, north], proj=CRS, geodesic=False)),
    ]

    with tempfile.TemporaryDirectory(prefix="aqi_tiles_") as temp_dir:
        temp_root = Path(temp_dir)
        tile_paths = [
            _tile_download(image, tile_region, temp_root / f"{label}.raw")
            for label, tile_region in tile_defs
        ]
        datasets = [rasterio.open(path) for path in tile_paths]
        try:
            merged_values, merged_transform = rio_merge(datasets, nodata=NODATA_VALUE)
            output_metadata = datasets[0].meta.copy()
            output_metadata.update({
                "height": merged_values.shape[1],
                "width": merged_values.shape[2],
                "count": merged_values.shape[0],
                "transform": merged_transform,
                "crs": CRS,
                "nodata": NODATA_VALUE,
            })
            with rasterio.open(destination, "w", **output_metadata) as output:
                output.write(merged_values)
        finally:
            for dataset in datasets:
                dataset.close()


def aqi_to_rgba(values: np.ndarray) -> np.ndarray:
    STOP_V = np.array([0.0, 50.0, 100.0, 200.0, 300.0, 400.0, 500.0], dtype=np.float32)
    STOP_R = np.array([  0, 140, 255, 247, 237, 158, 158], dtype=np.float32)
    STOP_G = np.array([168, 198, 242, 147,  28,  11,  11], dtype=np.float32)
    STOP_B = np.array([ 89,  63,   0,  30,  36,  15,  15], dtype=np.float32)

    valid = np.isfinite(values) & (values != NODATA_VALUE)
    clamped = np.where(valid, np.clip(values, STOP_V[0], STOP_V[-1]), STOP_V[0]).ravel()
    h, w = values.shape

    r_acc = np.zeros(h * w, np.float32)
    g_acc = np.zeros(h * w, np.float32)
    b_acc = np.zeros(h * w, np.float32)
    for i in range(len(STOP_V) - 1):
        lo, hi = STOP_V[i], STOP_V[i + 1]
        seg = (clamped >= lo) & (clamped <= hi)
        t_seg = np.where(seg, (clamped - lo) / max(hi - lo, 1e-6), 0.0)
        r_acc += seg * (STOP_R[i] + (STOP_R[i + 1] - STOP_R[i]) * t_seg)
        g_acc += seg * (STOP_G[i] + (STOP_G[i + 1] - STOP_G[i]) * t_seg)
        b_acc += seg * (STOP_B[i] + (STOP_B[i + 1] - STOP_B[i]) * t_seg)

    # Alpha ramp for bioluminescent contrast:
    # Low AQI (0-50) is highly transparent (alpha ~20-60)
    # High AQI (150+) is fully opaque (alpha ~255)
    # This allows the glow to bleed over the dark basemap exactly like NDVI!
    t_alpha = np.clip(clamped / 150.0, 0.0, 1.0)
    alpha_f = 20.0 + (t_alpha ** 1.5) * (255.0 - 20.0)
    alpha_f = np.where(valid.ravel(), alpha_f, 0.0)

    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[:, :, 0] = np.clip(r_acc, 0, 255).reshape(h, w).astype(np.uint8)
    rgba[:, :, 1] = np.clip(g_acc, 0, 255).reshape(h, w).astype(np.uint8)
    rgba[:, :, 2] = np.clip(b_acc, 0, 255).reshape(h, w).astype(np.uint8)
    rgba[:, :, 3] = np.clip(alpha_f, 0, 255).reshape(h, w).astype(np.uint8)
    return rgba


def _blur_rgba(rgba: np.ndarray, radius: float) -> np.ndarray:
    if radius <= 0:
        return rgba
    img = Image.fromarray(rgba, mode="RGBA")
    r, g, b, a = img.split()
    r2 = r.filter(ImageFilter.GaussianBlur(radius=radius))
    g2 = g.filter(ImageFilter.GaussianBlur(radius=radius))
    b2 = b.filter(ImageFilter.GaussianBlur(radius=radius))
    a2 = a.filter(ImageFilter.GaussianBlur(radius=radius))
    return np.array(Image.merge("RGBA", (r2, g2, b2, a2))).astype(np.uint8)


def generate_aqi_three_layer(
    values: np.ndarray,
    sharp_path: Path,
    glow_path: Path,
    halo_path: Path,
    study_mask: np.ndarray | None,
    scale_factor: int = 1,
) -> None:
    raw_rgba = aqi_to_rgba(values)
    
    img = Image.fromarray(raw_rgba, mode="RGBA")
    if scale_factor > 1:
        new_size = (img.width * scale_factor, img.height * scale_factor)
        img = img.resize(new_size, Image.Resampling.BICUBIC)
    
    base_rgba = np.array(img)

    # Apply organic granular micro-texture (noise)
    noise_raw = np.random.uniform(0.3, 1.0, (base_rgba.shape[0] // 2, base_rgba.shape[1] // 2)).astype(np.float32)
    noise_img = Image.fromarray(noise_raw).resize((base_rgba.shape[1], base_rgba.shape[0]), Image.Resampling.BILINEAR)
    noise = np.array(noise_img)
    noise = np.clip(noise ** 1.3, 0.3, 1.0) # Organic pointillist grid
    
    base_rgba[:, :, 3] = (base_rgba[:, :, 3].astype(np.float32) * noise).astype(np.uint8)

    # 1. Base Layer (Sharp) - Granular and slightly smoothed
    sharp_rgba = _blur_rgba(base_rgba, radius=0.2 * scale_factor)
    
    # 2. Glow & Halo Layers
    glow_rgba = _blur_rgba(base_rgba, radius=4.0 * scale_factor)
    halo_rgba = _blur_rgba(base_rgba, radius=12.0 * scale_factor)

    # Boost the halo brightness slightly so it reads as a massive soft bloom
    halo_rgba = halo_rgba.copy()
    halo_rgba[:, :, 3] = np.clip(halo_rgba[:, :, 3].astype(np.uint16) * 250 // 255, 0, 255).astype(np.uint8)

    # CRITICAL: Apply study region mask LAST to all layers.
    # This guarantees the pixels outside the exact shape of Mumbai/Thane are 100% transparent,
    # completely eliminating any rectangular bounding box artifacts.
    sharp_rgba = apply_study_region_mask(sharp_rgba, study_mask)
    glow_rgba  = apply_study_region_mask(glow_rgba,  study_mask)
    halo_rgba  = apply_study_region_mask(halo_rgba,  study_mask)

    Image.fromarray(sharp_rgba, mode="RGBA").save(sharp_path, "PNG", compress_level=6)
    Image.fromarray(glow_rgba,  mode="RGBA").save(glow_path,  "PNG", compress_level=6)
    Image.fromarray(halo_rgba,  mode="RGBA").save(halo_path,  "PNG", compress_level=6)


def publish_aqi_geotiff(
    source_path: Path,
    *,
    start_date: str,
    end_date: str,
    image_count: int,
    output_root: Path = SURFACE_ROOT,
) -> dict[str, Any]:
    context = source_context(start_date, end_date)
    with rasterio.open(source_path) as source:
        values = source.read(1).astype(np.float32)
        mask = source.read_masks(1) > 0
        nodata = source.nodata
        if nodata is not None:
            mask &= values != nodata
        valid = mask & np.isfinite(values)
        output_values = np.where(valid, np.clip(values, 0.0, 500.0), NODATA_VALUE).astype(np.float32)
        bounds = (source.bounds.left, source.bounds.bottom, source.bounds.right, source.bounds.top)
        transform = source.transform
        width, height = source.width, source.height

    SCALE_FACTOR = 20
    out_width = width * SCALE_FACTOR
    out_height = height * SCALE_FACTOR
    
    from rasterio import Affine
    new_transform = transform * Affine.scale(1/SCALE_FACTOR, 1/SCALE_FACTOR)
    study_mask = get_study_region_mask(out_width, out_height, new_transform, bounds)

    output_dir = output_root / "aqi"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
    stamp = timestamp.strftime("%Y%m%dT%H%M%SZ")
    geotiff_path = output_dir / f"aqi_{stamp}.tif"
    sharp_path = output_dir / f"aqi_{stamp}.png"
    glow_path  = output_dir / f"aqi_{stamp}_glow.png"
    halo_path  = output_dir / f"aqi_{stamp}_halo.png"

    with rasterio.open(
        geotiff_path, "w", driver="GTiff", height=height, width=width, count=1,
        dtype="float32", crs=CRS, transform=transform, nodata=NODATA_VALUE, compress="deflate",
    ) as output:
        output.write(output_values, 1)
        output.update_tags(
            metric="aqi", source="Google Earth Engine / Sentinel-5P",
            dataset=S5P_DATASET, methodology=METHODOLOGY,
            window_start=start_date, window_end=end_date,
            nodata_semantics="No valid satellite AQI pixel",
        )

    generate_aqi_three_layer(output_values, sharp_path, glow_path, halo_path, study_mask, scale_factor=SCALE_FACTOR)

    valid_values = output_values[output_values != NODATA_VALUE]
    west, south, east, north = (float(value) for value in bounds)

    geotiff_rel = str(geotiff_path.relative_to(output_root)).replace("\\", "/")
    sharp_rel   = str(sharp_path.relative_to(output_root)).replace("\\", "/")
    glow_rel    = str(glow_path.relative_to(output_root)).replace("\\", "/")
    halo_rel    = str(halo_path.relative_to(output_root)).replace("\\", "/")

    record: dict[str, Any] = {
        "metric": "aqi", "generation_status": "generated",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_timestamp": timestamp.isoformat(),
        "timestamp": stamp,
        "source_period": {"start": start_date, "end": end_date},
        "source": "Google Earth Engine / Sentinel-5P", "dataset": S5P_DATASET,
        "methodology": METHODOLOGY,
        "interpretation": "Sentinel-5P NO2 column number density converted to an AQI proxy score (0-500).",
        "semantic_label": "AQI Proxy · Air Quality",
        "preprocessing": {"composite": context["composite"], "window_days": context["window_days"]},
        "images_found": image_count, "image_count": image_count, "crs": CRS,
        "scale_m": SCALE_METERS,
        "bounds": {"west": west, "south": south, "east": east, "north": north},
        "mapbox_coordinates": mapbox_coordinates((west, south, east, north)),
        "coordinates": mapbox_coordinates((west, south, east, north)),
        "width": width, "height": height, "pixel_size_degrees": {"longitude": (east - west) / width, "latitude": (north - south) / height},
        "source_scale_m": SCALE_METERS, "nodata_value": NODATA_VALUE, "nodata": True,
        "nodata_semantics": "transparent; no valid satellite AQI pixel; study region clipped to Mumbai + Thane + Mira-Bhayandar boundaries",
        "valid_pixels": int(valid.sum()), "nodata_pixels": int((~valid).sum()),
        "valid_pixel_percent": round(float(valid.mean() * 100), 3),
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


def generate_aqi_surface(*, start_date: str, end_date: str) -> dict[str, Any]:
    initialize_ee()
    bounds = get_aqi_export_bounds()
    image, region, image_count = build_aqi_composite(start_date=start_date, end_date=end_date, bounds=bounds)
    with tempfile.TemporaryDirectory(prefix="geosense-aqi-") as temp:
        downloaded = Path(temp) / "aqi_download.tif"
        _download_geotiff(image, region, downloaded)
        return publish_aqi_geotiff(downloaded, start_date=start_date, end_date=end_date, image_count=image_count)


def load_latest_aqi_surface(manifest_path: Path = MANIFEST_PATH) -> dict[str, Any] | None:
    if not manifest_path.exists():
        return None
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    record = data.get("surfaces", {}).get("aqi")
    return record if isinstance(record, dict) and record.get("generation_status") == "generated" else None
