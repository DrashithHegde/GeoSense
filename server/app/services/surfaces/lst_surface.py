"""Static Landsat 8/9 LST surface artifacts for Mapbox.

This module builds continuous land-surface temperature rasters suitable for
thermal-style visualization. It reuses the established Landsat C2 L2 preprocessing
from gee/ingest_lst.py and writes derived visualization files (GeoTIFF + PNG + glow).

The frozen zone geometry is used solely to obtain the existing study extent for
a rectangular satellite export. This does not read zone averages as pixels nor
write to the database.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any
import zipfile
import os

import ee
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter

_RASTERIO_PROJ_DATA = Path(sys.prefix) / "Lib" / "site-packages" / "rasterio" / "proj_data"
if _RASTERIO_PROJ_DATA.is_dir():
    os.environ["PROJ_LIB"] = str(_RASTERIO_PROJ_DATA)
    os.environ["PROJ_DATA"] = str(_RASTERIO_PROJ_DATA)
import rasterio
from rasterio.features import geometry_mask
from shapely.geometry import mapping
import requests

from app.services.municipality_boundaries import (
    get_study_region_bounds,
    load_municipality_boundaries,
    load_study_region_geometry,
)
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
LST_VISUAL_SMOOTHING_SIGMA = 0.8
LST_GLOW_SMOOTHING_SIGMA = 1.4
LST_GLOW_PERCENTILE = 90.0
LST_GLOW_ALPHA_MAX = 64
LST_RASTER_ALPHA = 220
LST_COLOR_STOPS = (
    (0.00, (37, 99, 235), "Cool"),
    (0.20, (6, 182, 212), "Cool"),
    (0.45, (250, 204, 21), "Moderate"),
    (0.70, (249, 115, 22), "Hot"),
    (0.88, (239, 68, 68), "Very hot"),
    (1.00, (127, 29, 29), "Very hot"),
)


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
    """Return the bounds of the validated Mumbai + Thane + Mira-Bhayandar union."""
    return get_study_region_bounds()


def get_lst_export_aoi():
    """Build the Earth Engine geometry from the shared municipality union."""
    return ee.Geometry(mapping(load_study_region_geometry()), proj=CRS, geodesic=False)


def _build_lst_collection(*, start_date: str, end_date: str, region):
    source_context(start_date, end_date)
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
    return l8.merge(l9)


def build_lst_composite(*, start_date: str, end_date: str, region=None):
    """Build the established cloud-masked Landsat 8/9 LST composite."""
    region = region or get_lst_export_aoi()
    collection = _build_lst_collection(start_date=start_date, end_date=end_date, region=region)
    return collection.map(mask_landsat_l2).map(add_lst_celsius).median().select("LST")


def _smooth_lst_visualization(values: np.ndarray, valid_mask: np.ndarray) -> np.ndarray:
    """Smooth only valid visualization values with normalized Gaussian weights."""
    weights = gaussian_filter(valid_mask.astype(np.float32), LST_VISUAL_SMOOTHING_SIGMA, mode="nearest")
    weighted_values = gaussian_filter(
        np.where(valid_mask, values, 0.0).astype(np.float32),
        LST_VISUAL_SMOOTHING_SIGMA,
        mode="nearest",
    )
    smoothed = np.full(values.shape, NODATA_VALUE, dtype=np.float32)
    smoothed[valid_mask] = weighted_values[valid_mask] / np.maximum(weights[valid_mask], 1e-6)
    return smoothed


def _color_stop_metadata(min_c: float, max_c: float) -> list[dict[str, Any]]:
    span = max(max_c - min_c, 1e-6)
    stops = []
    for position, (red, green, blue), label in LST_COLOR_STOPS:
        stops.append({
            "position": position,
            "temperature_c": round(min_c + span * position, 1),
            "color": f"#{red:02x}{green:02x}{blue:02x}",
            "label": label,
        })
    return stops


def lst_to_rgba(
    values: np.ndarray,
    *,
    min_c: float,
    max_c: float,
    valid_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Color a visualization raster while keeping NoData fully transparent."""
    valid = np.isfinite(values) & (values != NODATA_VALUE)
    if valid_mask is not None:
        valid &= valid_mask
    span = max(max_c - min_c, 1e-6)
    normalized = np.clip((values.astype(np.float32) - min_c) / span, 0.0, 1.0)
    positions = np.array([stop[0] for stop in LST_COLOR_STOPS], dtype=np.float32)
    colors = np.array([stop[1] for stop in LST_COLOR_STOPS], dtype=np.float32)

    rgba = np.zeros((*values.shape, 4), dtype=np.uint8)
    for channel in range(3):
        rgba[:, :, channel] = np.interp(normalized, positions, colors[:, channel]).astype(np.uint8)
    rgba[:, :, 3] = np.where(valid, LST_RASTER_ALPHA, 0).astype(np.uint8)
    return rgba


def _write_lst_visualizations(
    values: np.ndarray,
    valid_mask: np.ndarray,
    output_dir: Path,
    timestamp_str: str,
) -> dict[str, Any]:
    valid_values = values[valid_mask]
    min_c = float(valid_values.min())
    max_c = float(valid_values.max())
    smoothed = _smooth_lst_visualization(values, valid_mask)

    sharp_path = output_dir / f"lst_{timestamp_str}.png"
    sharp_rgba = lst_to_rgba(smoothed, min_c=min_c, max_c=max_c, valid_mask=valid_mask)
    sharp_rgba[~valid_mask, 3] = 0
    Image.fromarray(sharp_rgba, mode="RGBA").save(sharp_path, "PNG", compress_level=6)

    glow_path = output_dir / f"lst_{timestamp_str}_glow.png"
    threshold_c = float(np.percentile(valid_values, LST_GLOW_PERCENTILE))
    hot_mask = valid_mask & (smoothed >= threshold_c)
    glow_rgba = lst_to_rgba(smoothed, min_c=min_c, max_c=max_c, valid_mask=hot_mask)
    normalized = np.clip((smoothed - min_c) / max(max_c - min_c, 1e-6), 0.0, 1.0)
    threshold_t = float(np.clip((threshold_c - min_c) / max(max_c - min_c, 1e-6), 0.0, 1.0))
    hot_intensity = np.where(
        hot_mask,
        (normalized - threshold_t) / max(1.0 - threshold_t, 1e-6),
        0.0,
    )
    blurred_alpha = gaussian_filter(
        (hot_intensity * LST_GLOW_ALPHA_MAX).astype(np.float32),
        LST_GLOW_SMOOTHING_SIGMA,
        mode="nearest",
    )
    glow_rgba[:, :, 3] = np.where(
        valid_mask,
        np.clip(blurred_alpha, 0, LST_GLOW_ALPHA_MAX).astype(np.uint8),
        0,
    )
    Image.fromarray(glow_rgba, mode="RGBA").save(glow_path, "PNG", compress_level=6)

    return {
        "png_path": sharp_path,
        "glow_path": glow_path,
        "glow_threshold_c": round(threshold_c, 2),
        "color_stops": _color_stop_metadata(min_c, max_c),
    }


def regenerate_lst_visualizations() -> dict[str, Any]:
    """Regenerate only LST PNG artifacts from the published scientific TIFF."""
    record = load_latest_lst_surface()
    if record is None:
        raise FileNotFoundError("No published LST surface is available")

    output_dir = SURFACE_ROOT / "lst"
    tiff_path = output_dir / record["files"]["geotiff"]
    if not tiff_path.is_file():
        raise FileNotFoundError(f"Published scientific LST GeoTIFF is missing: {tiff_path}")
    with rasterio.open(tiff_path) as source:
        values = source.read(1)
        transform = source.transform
        if source.crs is None or source.crs.to_string() != CRS:
            raise ValueError(f"Published LST GeoTIFF must use {CRS}")
        valid_mask = source.read_masks(1) > 0
        valid_mask &= np.isfinite(values) & (values != NODATA_VALUE)

    union_mask = np.zeros(valid_mask.shape, dtype=bool)
    for municipality in load_municipality_boundaries():
        municipality_mask = geometry_mask(
            [municipality["geojson"]],
            out_shape=valid_mask.shape,
            transform=transform,
            invert=True,
            all_touched=True,
        )
        union_mask |= municipality_mask
        if not np.any(valid_mask & municipality_mask):
            raise ValueError(f"Published LST GeoTIFF has zero valid pixels inside {municipality['name']}")
    valid_mask &= union_mask

    timestamp_str = str(record["timestamp"])
    visualization = _write_lst_visualizations(values, valid_mask, output_dir, timestamp_str)
    record["glow_threshold_c"] = visualization["glow_threshold_c"]
    record["visualization"] = {
        "smoothing": "normalized Gaussian; visualization only",
        "smoothing_sigma_pixels": LST_VISUAL_SMOOTHING_SIGMA,
        "glow_smoothing_sigma_pixels": LST_GLOW_SMOOTHING_SIGMA,
        "color_stops": visualization["color_stops"],
        "nodata_semantics": "transparent; output alpha is masked to valid pixels in the municipality union",
    }
    record.setdefault("checksums", {})["png_sha256"] = _sha256(visualization["png_path"])
    record["checksums"]["glow_png_sha256"] = _sha256(visualization["glow_path"])
    _write_manifest(record, MANIFEST_PATH)
    return record


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
    if image_count <= 0:
        raise ValueError("LST export image count must be positive")

    with rasterio.open(source_path) as source:
        if source.count != 1:
            raise ValueError("LST export must contain exactly one raster band")
        if source.crs is None or source.crs.to_string() != CRS:
            raise ValueError(f"LST export must use {CRS}; got {source.crs}")

        values = source.read(1)
        source_mask = source.read_masks(1) > 0
        transform = source.transform
        bounds = source.bounds
        resolution = source.res
        source_nodata = source.nodata
        profile = source.profile.copy()
        profile["nodata"] = NODATA_VALUE

    expected_resolution = SCALE_METERS / 111319.49079327358
    if any(not math.isclose(abs(pixel_size), expected_resolution, rel_tol=0.02) for pixel_size in resolution):
        raise ValueError(
            f"LST export must be nominally {SCALE_METERS} m; received pixel size {resolution} in {CRS}"
        )

    expected_bounds = get_study_region_bounds()
    bounds_tolerance = max(abs(resolution[0]), abs(resolution[1])) * 1.5
    if (
        bounds.left > expected_bounds[0] + bounds_tolerance
        or bounds.bottom > expected_bounds[1] + bounds_tolerance
        or bounds.right < expected_bounds[2] - bounds_tolerance
        or bounds.top < expected_bounds[3] - bounds_tolerance
    ):
        raise ValueError(
            f"LST export bounds {tuple(bounds)} do not cover municipality union {expected_bounds}"
        )

    source_valid_mask = source_mask & np.isfinite(values) & (values != NODATA_VALUE)
    if source_nodata is not None:
        source_valid_mask &= values != source_nodata
    if not source_valid_mask.any():
        raise ValueError("LST export contains zero valid pixels")

    municipality_union_mask = np.zeros(source_valid_mask.shape, dtype=bool)
    valid_pixels_by_municipality: dict[str, int] = {}
    for municipality in load_municipality_boundaries():
        municipality_mask = geometry_mask(
            [municipality["geojson"]],
            out_shape=source_valid_mask.shape,
            transform=transform,
            invert=True,
            all_touched=True,
        )
        municipality_union_mask |= municipality_mask
        municipality_valid = int(np.count_nonzero(source_valid_mask & municipality_mask))
        valid_pixels_by_municipality[municipality["name"]] = municipality_valid
        if municipality_valid == 0:
            raise ValueError(f"LST export has zero valid pixels inside {municipality['name']}")

    valid_mask = source_valid_mask & municipality_union_mask
    valid_count = int(np.sum(valid_mask))
    if valid_count == 0:
        raise ValueError("LST export has zero valid pixels inside the municipality union")

    valid_values = values[valid_mask]
    lst_min = float(np.min(valid_values))
    lst_max = float(np.max(valid_values))
    lst_mean = float(np.mean(valid_values))
    lst_median = float(np.median(valid_values))
    nodata_count = int(valid_mask.size - valid_count)
    values = np.where(valid_mask, values, NODATA_VALUE)

    timestamp_str = datetime.fromisoformat(end_date).strftime("%Y%m%dT%H%M%SZ")
    output_dir = output_root / "lst"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Canonical GeoTIFF
    canonical_tiff = output_dir / f"lst_{timestamp_str}.tif"
    with rasterio.open(canonical_tiff, "w", **profile) as dest:
        dest.write(values, 1)

    visualization = _write_lst_visualizations(values, valid_mask, output_dir, timestamp_str)
    sharp_png = visualization["png_path"]
    glow_png = visualization["glow_path"]

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
        "total_pixels": int(valid_mask.size),
        "nodata_pixels": nodata_count,
        "valid_pixels_by_municipality": valid_pixels_by_municipality,
        "lst_min_c": round(lst_min, 2),
        "lst_max_c": round(lst_max, 2),
        "lst_mean_c": round(lst_mean, 2),
        "lst_median_c": round(lst_median, 2),
        "glow_threshold_c": visualization["glow_threshold_c"],
        "visualization": {
            "smoothing": "normalized Gaussian; visualization only",
            "smoothing_sigma_pixels": LST_VISUAL_SMOOTHING_SIGMA,
            "glow_smoothing_sigma_pixels": LST_GLOW_SMOOTHING_SIGMA,
            "color_stops": visualization["color_stops"],
            "nodata_semantics": "transparent; output alpha is masked to valid pixels in the municipality union",
        },
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

    _write_manifest(record, output_root / "manifest.json")

    return record


def generate_lst_surface(start_date: str, end_date: str) -> dict[str, Any]:
    """Export, download, validate, and publish a real Landsat LST surface."""
    initialize_ee()
    source_context(start_date, end_date)
    region = get_lst_export_aoi()
    collection = _build_lst_collection(start_date=start_date, end_date=end_date, region=region)
    image_count = int(collection.size().getInfo())
    if image_count == 0:
        raise RuntimeError(f"No Landsat 8/9 scenes intersect the municipality union for {start_date} to {end_date}")

    composite = (
        collection.map(mask_landsat_l2)
        .map(add_lst_celsius)
        .median()
        .select("LST")
        .clip(region)
        .unmask(NODATA_VALUE)
    )
    download_url = composite.getDownloadURL({
        "name": f"GeoSense_LST_{end_date}",
        "bands": ["LST"],
        "region": region,
        "scale": SCALE_METERS,
        "crs": CRS,
        "format": "ZIPPED_GEO_TIFF",
    })

    with tempfile.TemporaryDirectory(prefix="geosense-lst-") as temporary_directory:
        temporary_root = Path(temporary_directory)
        download_path = temporary_root / "lst_export.zip"
        geotiff_path = temporary_root / "lst_export.tif"
        with requests.get(download_url, timeout=(20, 300), stream=True) as response:
            response.raise_for_status()
            with download_path.open("wb") as download_file:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        download_file.write(chunk)

        if zipfile.is_zipfile(download_path):
            with zipfile.ZipFile(download_path) as archive:
                geotiff_members = [
                    member for member in archive.namelist()
                    if member.lower().endswith((".tif", ".tiff"))
                ]
                if len(geotiff_members) != 1:
                    raise ValueError(f"Expected one GeoTIFF in Earth Engine download, found {len(geotiff_members)}")
                with archive.open(geotiff_members[0]) as source_file, geotiff_path.open("wb") as output_file:
                    shutil.copyfileobj(source_file, output_file)
        else:
            shutil.copyfile(download_path, geotiff_path)

        return publish_lst_geotiff(
            geotiff_path,
            start_date=start_date,
            end_date=end_date,
            image_count=image_count,
        )


def load_latest_lst_surface() -> dict[str, Any] | None:
    """Load the latest LST surface metadata from manifest, or None if unavailable."""
    if not MANIFEST_PATH.exists():
        return None
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        return manifest.get("surfaces", {}).get("lst")
    except (OSError, json.JSONDecodeError):
        return None
