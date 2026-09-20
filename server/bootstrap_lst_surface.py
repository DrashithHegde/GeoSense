"""Bootstrap LST surface from existing zone LST data.

This creates an initial LST GeoTIFF by interpolating zone-level LST values
across the Mumbai region. This is a PLACEHOLDER for demonstration — the real
LST surface should come from the full Landsat 8/9 export via generate_lst_surface.py.

Usage:
    python bootstrap_lst_surface.py
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from scipy.interpolate import griddata
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).parent))

from app.database import engine
from app.services.surfaces.lst_surface import (
    SURFACE_ROOT,
    CRS,
    NODATA_VALUE,
    publish_lst_geotiff,
    get_lst_export_bounds,
)


def main() -> int:
    print("Bootstrapping LST surface from zone data...")

    # Fetch zone centroids + LST values
    query = text("""
        SELECT
            z.id,
            ST_X(ST_Centroid(z.geometry)) AS lng,
            ST_Y(ST_Centroid(z.geometry)) AS lat,
            e.lst,
            e.observed_at
        FROM zones z
        LEFT JOIN LATERAL (
            SELECT lst, observed_at
            FROM environment_data
            WHERE zone_id = z.id AND lst IS NOT NULL
            ORDER BY observed_at DESC
            LIMIT 1
        ) e ON true
        WHERE e.lst IS NOT NULL
    """)

    with engine.connect() as conn:
        rows = conn.execute(query).fetchall()

    if not rows:
        print("ERROR: No zones with LST data found")
        return 1

    print(f"Found {len(rows)} zones with LST data")

    # Extract coordinates and LST values
    points = np.array([(row[1], row[2]) for row in rows])  # (lng, lat)
    lst_values = np.array([row[3] for row in rows])
    observed_at = rows[0][4]  # Use the most common/recent timestamp

    print(f"LST range: {lst_values.min():.1f} – {lst_values.max():.1f} °C")
    print(f"LST mean: {lst_values.mean():.1f} °C")
    print(f"Observed at: {observed_at}")

    # Define grid bounds using the same expansion as lst_surface.py
    bounds = get_lst_export_bounds()

    # Create grid (30m resolution approximation at ~19°N)
    width = 1500
    height = 2000
    transform = from_bounds(*bounds, width, height)

    # Generate grid coordinates
    cols, rows = np.meshgrid(np.arange(width), np.arange(height))
    xs, ys = rasterio.transform.xy(transform, rows.ravel(), cols.ravel())
    grid_points = np.column_stack([xs, ys])

    # Interpolate LST values to grid using linear interpolation
    print("Interpolating LST values to grid...")
    grid_lst = griddata(
        points,
        lst_values,
        grid_points,
        method="linear",
        fill_value=NODATA_VALUE,
    )
    grid_lst = grid_lst.reshape(height, width).astype(np.float32)

    # Create output directory
    lst_dir = SURFACE_ROOT / "lst"
    lst_dir.mkdir(parents=True, exist_ok=True)

    # Write GeoTIFF
    timestamp_str = observed_at.strftime("%Y%m%dT%H%M%SZ")
    geotiff_path = lst_dir / f"lst_{timestamp_str}.tif"

    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": rasterio.float32,
        "crs": CRS,
        "transform": transform,
        "compress": "lzw",
        "nodata": NODATA_VALUE,
    }

    with rasterio.open(geotiff_path, "w", **profile) as dst:
        dst.write(grid_lst, 1)

    print(f"Created GeoTIFF: {geotiff_path}")

    # Publish (generate PNGs + manifest)
    start_date = (observed_at.date() - np.timedelta64(45, 'D')).isoformat()
    end_date = observed_at.date().isoformat()

    record = publish_lst_geotiff(
        geotiff_path,
        start_date=start_date,
        end_date=end_date,
        image_count=len(rows),  # approximation — actual would be satellite image count
    )

    print("\n✓ LST surface bootstrapped:")
    print(f"  GeoTIFF: {record['files']['geotiff']}")
    print(f"  Sharp PNG: {record['files']['png']}")
    print(f"  Glow PNG: {record['files']['glow_png']}")
    print(f"  LST range: {record['lst_min_c']:.1f} – {record['lst_max_c']:.1f} °C")
    print(f"  Valid pixels: {record['valid_pixels']:,}")
    print("\nNOTE: This is a placeholder surface interpolated from zone data.")
    print("For production, use generate_lst_surface.py with real Landsat 8/9 data.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
