"""Generate the 300 m analytical grid (spatial_cells) for one city.

Why 300 m:
- ~100 Landsat pixels (30 m LST) per cell -> robust zonal mean
- ~900 Sentinel-2 pixels (10 m NDVI) per cell -> good statistics
- neighbourhood scale; finer than AQI station spacing on purpose (AQI is interpolated)

The study region is the union of the city's municipality boundaries (data/.../boundaries/).
Cells are square in metres at the city's latitude, clipped to the region; fringe cells with
less than 1 % overlap are skipped. Cell codes are unique across cities (GSC-, DEL-, BLR-).

    python scripts/generate_spatial_cells.py --city delhi [--dry-run]
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT))

from shapely.geometry import box, mapping, shape  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.cities import get_city  # noqa: E402
from app.services.municipality_boundaries import load_municipality_boundaries, load_study_region_geometry  # noqa: E402

RESOLUTION_M = 300
CODE_PREFIX = {"mumbai": "GSC", "delhi": "DEL", "bengaluru": "BLR"}


def generate_grid() -> list[dict]:
    """300 m cells covering the current city's study region."""
    city = get_city()
    region = load_study_region_geometry()
    munis = [(b["name"], b["shapely_geom"]) for b in load_municipality_boundaries()]
    lat0 = (region.bounds[1] + region.bounds[3]) / 2.0
    d_lat = RESOLUTION_M / 111320.0
    d_lon = RESOLUTION_M / (111320.0 * math.cos(math.radians(lat0)))
    prefix = CODE_PREFIX.get(city.id, city.id[:3].upper())
    minx, miny, maxx, maxy = region.bounds

    cells = []
    lat = miny
    while lat < maxy:
        lon = minx
        while lon < maxx:
            cell = box(lon, lat, lon + d_lon, lat + d_lat)
            clipped = cell.intersection(region)
            if not clipped.is_empty and clipped.area >= cell.area * 0.01:
                c = clipped.centroid
                muni = next((n for n, g in munis if g.contains(c)), None)
                if muni is None:      # near a boundary: nearest municipality
                    muni = min(munis, key=lambda m: m[1].distance(c))[0]
                cells.append({"cell_code": f"{prefix}-{len(cells):06d}", "geometry": mapping(clipped),
                              "centroid_lon": c.x, "centroid_lat": c.y, "municipality_name": muni})
            lon += d_lon
        lat += d_lat
    return cells


def load_cells_to_db(cells: list[dict], db) -> int:
    city = get_city().id
    inserted = 0
    for c in cells:
        r = db.execute(text("""
            INSERT INTO spatial_cells (cell_code, geometry, centroid, resolution_m, municipality_name, city)
            VALUES (:code, ST_Multi(ST_GeomFromEWKT(:geom)), ST_GeomFromEWKT(:centroid), :res, :muni, :city)
            ON CONFLICT (cell_code) DO NOTHING
            RETURNING id
        """), {"code": c["cell_code"], "geom": f"SRID=4326;{shape(c['geometry']).wkt}",
               "centroid": f"SRID=4326;POINT({c['centroid_lon']} {c['centroid_lat']})",
               "res": RESOLUTION_M, "muni": c["municipality_name"], "city": city})
        inserted += r.rowcount or 0
    return inserted


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="build the grid but do not write to the database")
    args = ap.parse_args()

    city = get_city()
    cells = generate_grid()
    by_muni: dict[str, int] = {}
    for c in cells:
        by_muni[c["municipality_name"]] = by_muni.get(c["municipality_name"], 0) + 1
    print(f"{city.name}: {len(cells):,} cells of {RESOLUTION_M} m  " +
          ", ".join(f"{m}: {n:,}" for m, n in sorted(by_muni.items())))
    if args.dry_run:
        print("Dry run - nothing written.")
        return 0

    from app.database import get_db
    with get_db() as db:
        existing = db.execute(text("SELECT count(*) FROM spatial_cells WHERE city = :c"), {"c": city.id}).scalar()
        if existing:
            print(f"{city.name} already has {existing:,} cells - nothing to do (cells are never regenerated, "
                  "because every result is keyed to them).")
            return 0
        n = load_cells_to_db(cells, db)
        db.commit()
    print(f"Inserted {n:,} cells for {city.name}.")
    return 0


if __name__ == "__main__":
    from app.core.cities import run_script_for_city  # noqa: E402
    raise SystemExit(run_script_for_city(main))
