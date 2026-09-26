"""Regenerate surface PNG visualisation artifacts (sharp/glow/halo) from EXISTING
scientific GeoTIFFs on disk. Does NOT call Google Earth Engine, does NOT rewrite
GeoTIFF pixel values, does NOT touch database content.

Use case: when the visualisation pipeline (colour ramp, blur radii, boundary
masking, percentile normalisation) changes but the underlying Sentinel-2 data
is unchanged.

Expected inputs on disk (paths auto-discovered via latest manifest):
  - server/data/surfaces/ndvi/ndvi_YYYYMMDDT*.tif
  - server/data/surfaces/water-health/wh_YYYYMMDDT*.tif

Outputs (overwritten in-place):
  - *_sharp.png, *_glow.png, *_halo.png
  - updated manifest.json with new PNG filenames + checksums + visualisation metadata
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys

SERVER_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVER_ROOT.parent
for path in (str(REPO_ROOT), str(SERVER_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from app.services.surfaces.ndvi_surface import (
    SURFACE_ROOT as NDVI_SURFACE_ROOT,
    MANIFEST_PATH as NDVI_MANIFEST_PATH,
    publish_ndvi_geotiff,
    CRS as NDVI_CRS,
    NODATA_VALUE as NDVI_NODATA,
    SCALE_METERS as NDVI_SCALE,
    S2_DATASET as NDVI_DATASET,
    METHODOLOGY as NDVI_METHODOLOGY,
    COMPOSITE_WINDOW_DAYS as NDVI_COMPOSITE_DAYS,
)
from app.services.surfaces.water_health_surface import (
    SURFACE_ROOT as WH_SURFACE_ROOT,
    MANIFEST_PATH as WH_MANIFEST_PATH,
    publish_water_health_geotiff,
    CRS as WH_CRS,
    NODATA_VALUE as WH_NODATA,
    SCALE_METERS as WH_SCALE,
    S2_DATASET as WH_DATASET,
    METHODOLOGY as WH_METHODOLOGY,
    COMPOSITE_WINDOW_DAYS as WH_COMPOSITE_DAYS,
    source_context as wh_source_context,
)
import rasterio


_STAMP_RE = re.compile(r"(\d{8}T\d{6}Z)")


def _find_latest_tif(folder: Path, prefix: str) -> Path:
    tifs = sorted(folder.glob(f"{prefix}_*.tif"))
    if not tifs:
        raise FileNotFoundError(f"No {prefix} GeoTIFF found in {folder}")
    return tifs[-1]


def _stamp_from_path(path: Path) -> str:
    m = _STAMP_RE.search(path.name)
    if not m:
        raise ValueError(f"Cannot extract YYYYMMDDTHHMMSSZ stamp from {path.name}")
    return m.group(1)


def _stamp_to_end_date(stamp: str) -> str:
    dt = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    return dt.date().isoformat()


def regenerate_ndvi() -> dict:
    folder = NDVI_SURFACE_ROOT / "ndvi"
    tif_path = _find_latest_tif(folder, "ndvi")
    stamp = _stamp_from_path(tif_path)
    end_date = _stamp_to_end_date(stamp)
    # Compute start_date by subtracting the standard composite window so the
    # source_context guard (exactly COMPOSITE_WINDOW_DAYS) passes.
    end_dt = datetime.fromisoformat(end_date).date()
    start_date = (end_dt - timedelta(days=NDVI_COMPOSITE_DAYS)).isoformat()
    with rasterio.open(tif_path) as src:
        tags = src.tags()
    image_count = int(tags.get("IMAGE_COUNT", "0")) or 1
    record = publish_ndvi_geotiff(
        tif_path,
        start_date=start_date,
        end_date=end_date,
        image_count=image_count,
        output_root=NDVI_SURFACE_ROOT,
    )
    return {"ndvi": {"source_tif": str(tif_path), "stamp": record.get("timestamp")}}


def regenerate_water_health() -> dict:
    folder = WH_SURFACE_ROOT / "water-health"
    tif_path = _find_latest_tif(folder, "wh")
    stamp = _stamp_from_path(tif_path)
    end_date = _stamp_to_end_date(stamp)
    end_dt = datetime.fromisoformat(end_date).date()
    start_date = (end_dt - timedelta(days=WH_COMPOSITE_DAYS)).isoformat()
    with rasterio.open(tif_path) as src:
        tags = src.tags()
    image_count = int(tags.get("IMAGE_COUNT", "0")) or 1
    record = publish_water_health_geotiff(
        tif_path,
        start_date=start_date,
        end_date=end_date,
        image_count=image_count,
        output_root=WH_SURFACE_ROOT,
    )
    return {"water_health": {"source_tif": str(tif_path), "stamp": record.get("timestamp")}}


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Regenerate surface PNG layers only from existing GeoTIFFs.")
    parser.add_argument("--skip-ndvi", action="store_true")
    parser.add_argument("--skip-wh", action="store_true")
    args = parser.parse_args()

    summary: dict = {}
    if not args.skip_ndvi:
        print("[regenerate] NDVI surface PNGs ...")
        summary.update(regenerate_ndvi())
        print(f"          ✔ NDVI done: {summary['ndvi']}")
    if not args.skip_wh:
        print("[regenerate] Water Health surface PNGs ...")
        summary.update(regenerate_water_health())
        print(f"          ✔ Water Health done: {summary['water_health']}")

    print()
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
