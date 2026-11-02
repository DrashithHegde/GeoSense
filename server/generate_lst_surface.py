"""Generate LST surface for GeoSense — canonical GeoTIFF + visualization PNG + glow PNG.

Usage:
    python generate_lst_surface.py --start 2026-08-01 --end 2026-09-13

This script:
1. Requests a Landsat 8/9 LST composite export from Google Earth Engine
2. Waits for the export to complete
3. Downloads the result (manual step if using Drive export)
4. Generates the canonical GeoTIFF, sharp PNG, and glow PNG
5. Updates the surface manifest

The script uses the established 45-day composite window from gee/ingest_lst.py.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

# Add server root to path so imports resolve
sys.path.insert(0, str(Path(__file__).parent))

from app.services.surfaces.lst_surface import (
    COMPOSITE_WINDOW_DAYS,
    generate_lst_surface,
    publish_lst_geotiff,
    regenerate_lst_visualizations,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate LST surface for GeoSense")
    parser.add_argument("--start", help="Start date YYYY-MM-DD (default: 45 days before end)")
    parser.add_argument("--end", help="End date YYYY-MM-DD (default: today)")
    parser.add_argument(
        "--geotiff",
        help="Path to an already-downloaded real GEE LST GeoTIFF (skip the direct download)",
    )
    parser.add_argument("--image-count", type=int, help="Real Landsat scene count for a supplied --geotiff")
    parser.add_argument(
        "--visualize-current",
        action="store_true",
        help="Regenerate PNGs from the currently published scientific TIFF without rewriting it",
    )
    args = parser.parse_args()

    if args.visualize_current:
        try:
            record = regenerate_lst_visualizations()
            print("LST visualizations regenerated from the published scientific TIFF.")
            print(f"  Scientific TIFF unchanged: {record['files']['geotiff']}")
            print(f"  Temperature range: {record['lst_min_c']:.2f} to {record['lst_max_c']:.2f} °C")
            print(f"  Sharp PNG: {record['files']['png']}")
            print(f"  Glow PNG: {record['files']['glow_png']}")
            return 0
        except Exception as exc:
            print(f"ERROR: {exc}")
            import traceback
            traceback.print_exc()
            return 1

    today = datetime.now(timezone.utc).date()
    end = datetime.fromisoformat(args.end).date() if args.end else today
    start = (
        datetime.fromisoformat(args.start).date()
        if args.start
        else (end - timedelta(days=COMPOSITE_WINDOW_DAYS))
    )

    if (end - start).days != COMPOSITE_WINDOW_DAYS:
        print(f"ERROR: LST uses a fixed {COMPOSITE_WINDOW_DAYS}-day composite window.")
        print(f"  Received: {start} to {end} ({(end - start).days} days)")
        return 1

    start_str = start.isoformat()
    end_str = end.isoformat()

    if args.geotiff:
        if args.image_count is None or args.image_count <= 0:
            print("ERROR: --geotiff requires a positive --image-count from the matching Earth Engine collection.")
            return 1
        geotiff_path = Path(args.geotiff)
        if not geotiff_path.exists():
            print(f"ERROR: GeoTIFF not found: {geotiff_path}")
            return 1

        print(f"Publishing LST surface from existing GeoTIFF: {geotiff_path}")
        record = publish_lst_geotiff(
            geotiff_path,
            start_date=start_str,
            end_date=end_str,
            image_count=args.image_count,
        )
        print("✓ LST surface published:")
        print(f"  GeoTIFF: {record['files']['geotiff']}")
        print(f"  Sharp PNG: {record['files']['png']}")
        print(f"  Glow PNG: {record['files']['glow_png']}")
        print(f"  LST range: {record['lst_min_c']:.1f} – {record['lst_max_c']:.1f} °C")
        print(f"  LST mean: {record['lst_mean_c']:.1f} °C, median: {record['lst_median_c']:.1f} °C")
        print(f"  Valid pixels: {record['valid_pixels']:,}")
        print(f"  Glow threshold: {record['glow_threshold_c']:.1f} °C")
        return 0

    print(f"Generating LST surface: {start_str} to {end_str}")
    try:
        record = generate_lst_surface(start_str, end_str)
        print("LST surface exported, downloaded, validated, and published.")
        print(f"  Scene count: {record['image_count']}")
        print(f"  Source period: {record['source_period']['start']} to {record['source_period']['end']}")
        print(f"  Bounds: {record['bounds']}")
        print(f"  Valid pixels: {record['valid_pixels']:,}")
        print(f"  NoData pixels: {record['nodata_pixels']:,}")
        print(f"  Municipality coverage: {record['valid_pixels_by_municipality']}")
        print(f"  Temperature range: {record['lst_min_c']:.2f} to {record['lst_max_c']:.2f} °C")
        print(f"  GeoTIFF: {record['files']['geotiff']}")
        print(f"  Sharp PNG: {record['files']['png']}")
        print(f"  Glow PNG: {record['files']['glow_png']}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
