#!/usr/bin/env python3
"""Generate a Mumbai grid of ~N zones and optionally load into PostGIS.

Usage:
  python generate_zones.py --target-count 170 --out generated_zones.geojson --dry-run
  python generate_zones.py --target-count 170 --apply

This script defaults to the Mumbai bbox used by the legacy heatmap script when
no boundary GeoJSON is provided. It will never insert into the DB unless
`--apply` is passed explicitly.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from shapely.geometry import box, mapping, Polygon, MultiPolygon
from shapely.ops import unary_union
import geopandas as gpd


DEFAULT_BBOX = (72.77, 18.89, 72.95, 19.22)  # lon_min, lat_min, lon_max, lat_max


def make_grid(geom: Polygon, target_count: int = 170) -> gpd.GeoDataFrame:
    # Work in Web Mercator for metric distances
    gdf = gpd.GeoDataFrame(geometry=[geom], crs="EPSG:4326")
    gdf_m = gdf.to_crs(epsg=3857)
    poly = gdf_m.loc[0, "geometry"]
    area = poly.area
    if area <= 0:
        raise RuntimeError("Invalid geometry area computed.")

    cell_area = area / target_count
    cell_size = math.sqrt(cell_area)

    minx, miny, maxx, maxy = poly.bounds

    cells = []
    thresh = 0.1 * cell_area
    x = minx
    while x < maxx:
        y = miny
        while y < maxy:
            candidate = box(x, y, x + cell_size, y + cell_size)
            inter = candidate.intersection(poly)
            if not inter.is_empty and inter.area >= thresh:
                # ensure valid geometry and convert tiny slivers
                if isinstance(inter, Polygon):
                    geom_multi = MultiPolygon([inter])
                else:
                    geom_multi = inter if isinstance(inter, MultiPolygon) else MultiPolygon([inter])
                cells.append(geom_multi)
            y += cell_size
        x += cell_size

    gcells = gpd.GeoDataFrame(geometry=cells, crs="EPSG:3857")
    gcells = gcells.to_crs(epsg=4326)
    # merge tiny overlapping/adjacent pieces (optional)
    gcells["geometry"] = gcells["geometry"].apply(lambda g: g if g.is_valid else g.buffer(0))
    return gcells


def prepare_output(gcells: gpd.GeoDataFrame, prefix: str = "MUM") -> gpd.GeoDataFrame:
    rows = []
    for i, geom in enumerate(gcells.geometry, start=1):
        zone_code = f"{prefix}-{i:03d}"
        name = f"Zone {i:03d}"
        rows.append({"zone_code": zone_code, "name": name, "ward": None, "geometry": geom})
    out = gpd.GeoDataFrame(rows, crs=gcells.crs)
    return out


def insert_to_db(gdf: gpd.GeoDataFrame) -> None:
    # Import server app path to access the configured SQLAlchemy engine
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.database import engine

    # Ensure geometry column name is 'geometry' (GeoPandas default)
    # to_postgis will insert into the 'zones' table; use if_exists='append'
    gdf.to_postgis("zones", engine, if_exists="append", index=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", help="Path to Mumbai boundary GeoJSON (optional)")
    parser.add_argument("--target-count", type=int, default=170)
    parser.add_argument("--out", help="Write generated GeoJSON to this path")
    parser.add_argument("--dry-run", action="store_true", default=True, dest="dry_run")
    parser.add_argument("--apply", action="store_true", help="Apply changes to database (must be explicit)")
    args = parser.parse_args()

    if args.source:
        if not Path(args.source).exists():
            print(f"Source file {args.source} not found.")
            return
        src = gpd.read_file(args.source)
        if src.empty:
            print("Source boundary contains no features.")
            return
        boundary = unary_union(src.geometry.values)
    else:
        lonmin, latmin, lonmax, latmax = DEFAULT_BBOX
        boundary = box(lonmin, latmin, lonmax, latmax)

    print(f"Using boundary from {'source' if args.source else 'default bbox'}")

    cells = make_grid(boundary, target_count=args.target_count)
    # cells is in EPSG:4326 after conversion
    print(f"Generated {len(cells)} candidate cells")

    gdf_out = prepare_output(cells)

    # Basic validations
    dup_codes = gdf_out["zone_code"].duplicated().sum()
    print(f"Duplicate zone_code count (local): {dup_codes}")

    # Geometry checks
    invalid_count = gdf_out.geometry.is_valid.value_counts().get(False, 0)
    print(f"Invalid geometry count (local): {invalid_count}")

    if args.out:
        outp = Path(args.out)
        gdf_out.to_file(outp, driver="GeoJSON")
        print(f"Wrote GeoJSON to {outp}")

    if args.apply:
        print("Inserting into database (zones) — this will run in append mode.")
        insert_to_db(gdf_out)
        print("Insert complete.")
    else:
        print("Dry run only. No DB changes made. To insert, re-run with --apply")


if __name__ == "__main__":
    main()
