"""Generate a static AQI image surface from canonical OpenAQ/CPCB station AQI.

The GeoTIFF is a derived visualization/analysis artifact.  It never changes
the frozen analytical zones or raw observations, and its pixels are explicitly
IDW estimates rather than monitoring-station observations.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from statistics import mean
from typing import Any, Iterable

import numpy as np
from PIL import Image

# Windows PostgreSQL installations commonly export an older, incompatible
# PROJ_LIB.  Set Rasterio's bundled database *before importing Rasterio*, whose
# GDAL environment is initialized at import time.
_RASTERIO_PROJ_DATA = Path(sys.prefix) / "Lib" / "site-packages" / "rasterio" / "proj_data"
if _RASTERIO_PROJ_DATA.is_dir():
    os.environ["PROJ_LIB"] = str(_RASTERIO_PROJ_DATA)
    os.environ["PROJ_DATA"] = str(_RASTERIO_PROJ_DATA)
import rasterio
from rasterio.transform import from_bounds

from openaq.derive_aqi_grid import idw_estimate


# OpenAQ's existing MMR discovery extent.  This is a presentation extent, not
# a municipal mask or a replacement for the 189 analytical zones.
PRESENTATION_BOUNDS = (72.77, 18.89, 73.12, 19.40)  # west, south, east, north
DEFAULT_WIDTH = 160
DEFAULT_HEIGHT = 240
DEFAULT_K = 4
DEFAULT_MIN_STATIONS = 2
DEFAULT_POWER = 2.0
DEFAULT_MAX_DISTANCE_M = 15_000.0
NODATA_VALUE = -9999.0
CRS = "EPSG:4326"
METHODOLOGY = "OpenAQ CPCB AQI + IDW"
RASTERIO_PROJ_DATA = Path(rasterio.__file__).resolve().parent / "proj_data"

SERVER_ROOT = Path(__file__).resolve().parents[3]
SURFACE_ROOT = SERVER_ROOT / "data" / "surfaces"
AQI_ROOT = SURFACE_ROOT / "aqi"
MANIFEST_PATH = SURFACE_ROOT / "manifest.json"


@dataclass(frozen=True)
class AqiSurfaceConfig:
    bounds: tuple[float, float, float, float] = PRESENTATION_BOUNDS
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    k: int = DEFAULT_K
    min_stations: int = DEFAULT_MIN_STATIONS
    power: float = DEFAULT_POWER
    max_interpolation_distance_m: float = DEFAULT_MAX_DISTANCE_M


def mapbox_coordinates(bounds: tuple[float, float, float, float]) -> list[list[float]]:
    """Return Mapbox image-source corners: top-left, top-right, bottom-right, bottom-left."""
    west, south, east, north = bounds
    return [[west, north], [east, north], [east, south], [west, south]]


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _validate_station_points(stations: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    valid: list[dict[str, Any]] = []
    for station in stations:
        try:
            lat, lon, aqi = float(station["lat"]), float(station["lon"]), float(station["aqi"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (math.isfinite(lat) and math.isfinite(lon) and math.isfinite(aqi)):
            continue
        # The canonical CPCB implementation itself returns a 0..500 index.
        if not 0.0 <= aqi <= 500.0:
            continue
        valid.append({**station, "lat": lat, "lon": lon, "aqi": aqi})
    if not valid:
        raise ValueError("No finite CPCB AQI station points were supplied")
    return valid


def estimate_pixel_aqi(
    *, lat: float, lon: float, station_points: list[dict[str, Any]], config: AqiSurfaceConfig
) -> float | None:
    """Delegate interpolation to the canonical zone-IDW implementation."""
    value, _nearest, _used = idw_estimate(
        lat, lon, station_points, k=config.k,
        max_interp_distance_m=config.max_interpolation_distance_m,
        min_stations=config.min_stations, power=config.power,
    )
    return value


def generate_aqi_grid(
    station_points: Iterable[dict[str, Any]], config: AqiSurfaceConfig = AqiSurfaceConfig()
) -> np.ndarray:
    """Return a north-up grid with ``NODATA_VALUE`` outside station support."""
    stations = _validate_station_points(station_points)
    west, south, east, north = config.bounds
    if config.width <= 0 or config.height <= 0 or west >= east or south >= north:
        raise ValueError("Invalid AQI surface raster configuration")
    grid = np.full((config.height, config.width), NODATA_VALUE, dtype=np.float32)
    lon_step = (east - west) / config.width
    lat_step = (north - south) / config.height
    for row in range(config.height):
        lat = north - (row + 0.5) * lat_step
        for col in range(config.width):
            lon = west + (col + 0.5) * lon_step
            estimate = estimate_pixel_aqi(lat=lat, lon=lon, station_points=stations, config=config)
            if estimate is not None and math.isfinite(estimate):
                grid[row, col] = float(estimate)
    return grid


def _interpolate_color(value: float) -> tuple[int, int, int]:
    """AQI colours follow the existing GeoSense AQI stress ramp."""
    stops = (
        (0.0, (29, 209, 161)), (140.0, (255, 211, 42)),
        (225.0, (255, 140, 0)), (345.0, (255, 59, 59)),
        (420.0, (143, 63, 151)), (500.0, (126, 0, 35)),
    )
    value = max(0.0, min(500.0, value))
    for (left, c0), (right, c1) in zip(stops, stops[1:]):
        if value <= right:
            t = (value - left) / (right - left) if right > left else 0.0
            return tuple(round(a + (b - a) * t) for a, b in zip(c0, c1))
    return stops[-1][1]


def grid_to_rgba(grid: np.ndarray) -> np.ndarray:
    rgba = np.zeros((grid.shape[0], grid.shape[1], 4), dtype=np.uint8)
    valid = np.isfinite(grid) & (grid != NODATA_VALUE)
    for row, col in np.argwhere(valid):
        rgba[row, col, :3] = _interpolate_color(float(grid[row, col]))
        rgba[row, col, 3] = 255
    return rgba


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_manifest(record: dict[str, Any], manifest_path: Path = MANIFEST_PATH) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    current = {"version": 1, "surfaces": {}}
    if manifest_path.exists():
        try:
            current = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            raise ValueError(f"Existing surface manifest is invalid: {manifest_path}")
    current.setdefault("version", 1)
    current.setdefault("surfaces", {})["aqi"] = record
    temporary = manifest_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(manifest_path)


def generate_aqi_surface(
    station_points: Iterable[dict[str, Any]],
    *,
    source_timestamp: datetime,
    config: AqiSurfaceConfig = AqiSurfaceConfig(),
    output_root: Path = SURFACE_ROOT,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Write a GeoTIFF, transparent PNG and current manifest from real station points.

    This function is intentionally network-free: callers supply already-fetched
    canonical station points.  It writes only derived files under ``data/surfaces``.
    """
    stations = _validate_station_points(station_points)
    source_timestamp = _utc(source_timestamp)
    generated_at = datetime.now(timezone.utc)
    grid = generate_aqi_grid(stations, config)
    valid = grid != NODATA_VALUE
    if not valid.any():
        raise ValueError(
            "AQI surface has no supported pixels: insufficient eligible real stations "
            f"for minimum_stations={config.min_stations} within the configured IDW distance"
        )
    output_aqi_root = output_root / "aqi"
    output_aqi_root.mkdir(parents=True, exist_ok=True)
    stamp = source_timestamp.strftime("%Y%m%dT%H%M%SZ")
    tif_path = output_aqi_root / f"aqi_{stamp}.tif"
    png_path = output_aqi_root / f"aqi_{stamp}.png"
    transform = from_bounds(*config.bounds, config.width, config.height)

    # PostgreSQL/PostGIS can set PROJ_LIB globally on Windows.  Rasterio needs
    # its own compatible database; scope this override to raster creation.
    with rasterio.Env(PROJ_DATA=str(RASTERIO_PROJ_DATA), PROJ_LIB=str(RASTERIO_PROJ_DATA)):
        with rasterio.open(
            tif_path, "w", driver="GTiff", height=config.height, width=config.width,
            count=1, dtype="float32", crs=CRS, transform=transform, nodata=NODATA_VALUE,
            compress="deflate",
        ) as dataset:
            dataset.write(grid, 1)
            dataset.update_tags(
                metric="aqi", methodology=METHODOLOGY,
                generated_at=generated_at.isoformat(), source_timestamp=source_timestamp.isoformat(),
                idw_power=str(config.power), max_interpolation_distance_m=str(config.max_interpolation_distance_m),
                nodata_semantics="No station support; not zero or healthy AQI",
            )
    Image.fromarray(grid_to_rgba(grid), mode="RGBA").save(png_path)

    values = grid[valid]
    west, south, east, north = config.bounds
    record: dict[str, Any] = {
        "metric": "aqi", "generation_status": "generated",
        "generated_at": generated_at.isoformat(), "source_timestamp": source_timestamp.isoformat(),
        "source": "OpenAQ", "methodology": METHODOLOGY,
        "interpretation": "Spatially interpolated indicative AQI based on available real monitoring stations.",
        "idw": {"k": config.k, "power": config.power, "minimum_stations": config.min_stations,
                "max_interpolation_distance_m": config.max_interpolation_distance_m},
        "station_count": len(stations),
        "station_timestamp_range": {
            "oldest": min(_utc(s["observed_at"]) for s in stations if s.get("observed_at")).isoformat(),
            "newest": max(_utc(s["observed_at"]) for s in stations if s.get("observed_at")).isoformat(),
        },
        "crs": CRS, "bounds": {"west": west, "south": south, "east": east, "north": north},
        "mapbox_coordinates": mapbox_coordinates(config.bounds),
        "width": config.width, "height": config.height,
        "pixel_size_degrees": {"longitude": (east - west) / config.width, "latitude": (north - south) / config.height},
        "nodata_value": NODATA_VALUE, "nodata_semantics": "transparent; no eligible station support within configured IDW distance",
        "valid_pixels": int(valid.sum()), "nodata_pixels": int((~valid).sum()),
        "valid_pixel_percent": round(float(valid.mean() * 100), 3),
        "aqi_statistics": {"min": float(values.min()) if values.size else None,
                           "max": float(values.max()) if values.size else None,
                           "mean": float(values.mean()) if values.size else None},
        "geotiff_filename": str(tif_path.relative_to(output_root)).replace("\\", "/"),
        "png_filename": str(png_path.relative_to(output_root)).replace("\\", "/"),
        "checksums": {"geotiff_sha256": _sha256(tif_path), "png_sha256": _sha256(png_path)},
    }
    _write_manifest(record, manifest_path or output_root / "manifest.json")
    return record


def load_latest_aqi_surface(manifest_path: Path = MANIFEST_PATH) -> dict[str, Any] | None:
    if not manifest_path.exists():
        return None
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    record = data.get("surfaces", {}).get("aqi")
    return record if isinstance(record, dict) and record.get("generation_status") == "generated" else None
