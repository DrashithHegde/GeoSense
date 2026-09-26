"""Generate the 300m dense analytical grid for GeoSense spatial_cells table.

Scientific rationale for 300m resolution:
- Contains ~10 Landsat pixels (30m native LST resolution) → robust zonal mean
- Contains ~900 Sentinel-2 pixels (10m native NDVI resolution) → excellent statistics
- Matches neighborhood-scale AQI spatial variation
- 705 km² study area / 0.09 km² per cell ≈ 7,833 cells before boundary clipping

Study region: Mumbai + Thane + Mira-Bhayandar
Boundary files: server/data/boundaries/{mumbai,thane,mira_bhayandar}.geojson

Usage:
    python server/scripts/generate_spatial_cells.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(SERVER_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from shapely.geometry import shape, box, mapping
from shapely.ops import unary_union
from sqlalchemy import text

from app.database import engine, get_db

RESOLUTION_M = 300
BOUNDARIES_DIR = SERVER_ROOT / "data" / "boundaries"
MUNICIPALITY_FILES = {
    "Mumbai": BOUNDARIES_DIR / "mumbai.geojson",
    "Mira-Bhayandar": BOUNDARIES_DIR / "mira_bhayandar.geojson",
    "Thane": BOUNDARIES_DIR / "thane.geojson",
}

# Approximate degrees per meter at ~19°N
DEG_PER_M_LAT = 1.0 / 111320.0
DEG_PER_M_LON = 1.0 / (111320.0 * np.cos(np.radians(19.1)))

CELL_SIZE_LAT = RESOLUTION_M * DEG_PER_M_LAT
CELL_SIZE_LON = RESOLUTION_M * DEG_PER_M_LON


def load_boundaries() -> dict[str, object]:
    """Load and validate municipality boundaries."""
    geoms = {}
    for name, path in MUNICIPALITY_FILES.items():
        if not path.exists():
            raise FileNotFoundError(f"Boundary file not found: {path}")
        with open(path) as f:
            fc = json.load(f)
        features = fc.get("features", [])
        if not features:
            raise ValueError(f"No features in {path}")
        geom = unary_union([shape(feat["geometry"]) for feat in features])
        geoms[name] = geom
        area_km2 = geom.area * (111320.0 ** 2) / 1e6  # very rough
        print(f"  {name}: ~{area_km2:.0f} km² (rough WGS84 estimate)")
    return geoms


def generate_grid(study_region: object, municipality_geoms: dict[str, object]) -> list[dict]:
    """Generate 300m cells covering the study region."""
    bounds = study_region.bounds  # minx, miny, maxx, maxy
    minx, miny, maxx, maxy = bounds

    cells = []
    cell_idx = 0
    row = 0
    lat = miny
    while lat < maxy:
        lon = minx
        col = 0
        while lon < maxx:
            cell_geom = box(lon, lat, lon + CELL_SIZE_LON, lat + CELL_SIZE_LAT)
            # Clip to study region boundary
            clipped = cell_geom.intersection(study_region)
            if clipped.is_empty or clipped.area < (cell_geom.area * 0.01):
                # Skip cells with < 1% overlap (boundary fringe cells)
                lon += CELL_SIZE_LON
                col += 1
                continue

            # Determine municipality (centroid-based)
            centroid = clipped.centroid
            muni_name = None
            for mname, mgeom in municipality_geoms.items():
                if mgeom.contains(centroid):
                    muni_name = mname
                    break
            if muni_name is None:
                # Near boundary — assign to nearest municipality
                min_dist = float("inf")
                for mname, mgeom in municipality_geoms.items():
                    d = mgeom.distance(centroid)
                    if d < min_dist:
                        min_dist = d
                        muni_name = mname

            cell_code = f"GSC-{cell_idx:06d}"
            cells.append({
                "cell_code": cell_code,
                "geometry": mapping(clipped),
                "centroid_lon": centroid.x,
                "centroid_lat": centroid.y,
                "resolution_m": RESOLUTION_M,
                "municipality_name": muni_name,
            })
            cell_idx += 1
            lon += CELL_SIZE_LON
            col += 1
        lat += CELL_SIZE_LAT
        row += 1

    return cells


def load_cells_to_db(cells: list[dict], db) -> int:
    """Insert cells into spatial_cells table (skips duplicates by cell_code)."""
    inserted = 0
    for c in cells:
        geom_wkt = f"SRID=4326;{shape(c['geometry']).wkt}"
        centroid_wkt = f"SRID=4326;POINT({c['centroid_lon']} {c['centroid_lat']})"
        result = db.execute(
            text("""
                INSERT INTO spatial_cells (cell_code, geometry, centroid, resolution_m, municipality_name)
                VALUES (:code, ST_Multi(ST_GeomFromEWKT(:geom)), ST_GeomFromEWKT(:centroid), :res, :muni)
                ON CONFLICT (cell_code) DO NOTHING
                RETURNING id
            """),
            {
                "code": c["cell_code"],
                "geom": geom_wkt,
                "centroid": centroid_wkt,
                "res": c["resolution_m"],
                "muni": c["municipality_name"],
            }
        )
        if result.rowcount > 0:
            inserted += 1
    return inserted


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate 300m spatial_cells grid for GeoSense")
    parser.add_argument("--dry-run", action="store_true", help="Generate grid but do not insert into DB")
    args = parser.parse_args()

    print("Loading municipality boundaries...")
    municipality_geoms = load_boundaries()

    print("Computing study region union...")
    study_region = unary_union(list(municipality_geoms.values()))
    area_km2 = study_region.area * (111320.0 ** 2) / 1e6
    print(f"Study region total area: ~{area_km2:.0f} km²")

    print(f"Generating {RESOLUTION_M}m grid...")
    cells = generate_grid(study_region, municipality_geoms)
    print(f"Generated {len(cells)} cells")

    # Stats by municipality
    by_muni: dict[str, int] = {}
    for c in cells:
        by_muni[c["municipality_name"]] = by_muni.get(c["municipality_name"], 0) + 1
    for mname, count in sorted(by_muni.items()):
        print(f"  {mname}: {count} cells")

    if args.dry_run:
        print("DRY RUN — no DB writes. Done.")
        return 0

    print("Loading cells into spatial_cells table...")
    with get_db() as db:
        inserted = load_cells_to_db(cells, db)
        db.commit()

    print(f"Inserted {inserted} new cells into spatial_cells (skipped duplicates)")

    # Verify spatial index exists
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT COUNT(*) FROM spatial_cells
        """)).scalar()
        print(f"Total cells in DB: {row}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
