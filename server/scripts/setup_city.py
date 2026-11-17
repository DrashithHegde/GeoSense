"""Build every GeoSense layer for one city, in order, with the same pipeline as Mumbai.

    python scripts/setup_city.py --city delhi
    python scripts/setup_city.py --city bengaluru --skip history
    python scripts/setup_city.py --city delhi --from render          # resume from a step
    python scripts/setup_city.py --city delhi --only aqi composite ml

Needs (from server/, with the repo-root .env): the database migrated (alembic upgrade head),
Earth Engine credentials (earthengine authenticate; GEE_PROJECT) for the satellite steps, and
OPENAQ_AQI_KEY for AQI. Every step is a normal script you can also run on its own with --city.
Nothing is ever filled in: a layer without enough real data is recorded as unavailable.

Steps
  boundaries  study-region boundary file (Delhi / Bengaluru from DataMeet; Mumbai's ships with the repo)
  cells       300 m analytical grid in PostGIS                     scripts/generate_spatial_cells.py
  ndvi        Sentinel-2 NDVI, 14-day median, 10 m (Earth Engine) scripts/generate_ndvi_surface.py
  water       Sentinel-2 Water Health, 10 m (Earth Engine)         scripts/generate_water_health_surface.py
  lst         Landsat 8/9 LST, 45-day median, 30 m (Earth Engine)  scripts/generate_lst_surface.py
  indices     Sentinel-2 NDMI (NDBI = -NDMI), 20 m (Earth Engine)  scripts/generate_index_surfaces.py
  render      map images for NDVI / Water Health / LST             scripts/render_heatmaps.py
  aqi         OpenAQ CPCB stations -> CPCB AQI -> IDW              scripts/generate_aqi_station_surface.py
  composite   heat + surface + air composite                       scripts/generate_composite_surface.py
  validation  ESA WorldCover shares per cell (Earth Engine)        scripts/build_validation_reference.py
  ml          cell features, Isolation Forests, XGBoost, WH z      scripts/run_ml_pipeline.py
  history     seasonal history since 2023 (Earth Engine + OpenAQ)  scripts/build_history.py
  prune       remove map files no layer uses any more              scripts/prune_surfaces.py
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT))

from app.core.cities import CITIES, get_city  # noqa: E402

STEPS: list[tuple[str, list[str], bool]] = [
    # (name, command, may fail without stopping the run)
    ("boundaries", ["scripts/import_city_boundaries.py"], False),
    ("cells", ["scripts/generate_spatial_cells.py"], False),
    ("ndvi", ["scripts/generate_ndvi_surface.py"], False),
    ("water", ["scripts/generate_water_health_surface.py"], False),
    ("lst", ["scripts/generate_lst_surface.py"], False),
    ("indices", ["scripts/generate_index_surfaces.py"], True),
    ("render", ["scripts/render_heatmaps.py", "--only", "ndvi", "--only", "water_health", "--only", "lst"], False),
    ("aqi", ["scripts/generate_aqi_station_surface.py"], True),   # too few fresh stations = recorded, not fatal
    ("composite", ["scripts/generate_composite_surface.py"], False),
    ("validation", ["scripts/build_validation_reference.py"], True),
    ("ml", ["scripts/run_ml_pipeline.py"], False),
    ("history", ["scripts/build_history.py"], True),
    ("prune", ["scripts/prune_surfaces.py"], True),
]
NAMES = [s[0] for s in STEPS]


def run(name: str, cmd: list[str], city: str) -> int:
    if name == "boundaries":
        c = get_city(city)
        missing = [m for m, _ in c.municipalities if not (c.data_dir / "boundaries" / f"{m}.geojson").is_file()]
        if not missing:
            print(f"  boundaries present for {c.name}")
            return 0
        if city == "mumbai":
            print("  Mumbai's boundary files ship with the repository (data/boundaries/); restore them from git.")
            return 1
        full = [sys.executable, *cmd, "--city", city]
    else:
        full = [sys.executable, *cmd, "--city", city]
    print("  $ " + " ".join(full[1:]))
    return subprocess.call(full, cwd=SERVER_ROOT)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--city", required=True, choices=sorted(CITIES))
    ap.add_argument("--from", dest="start", choices=NAMES, help="start at this step")
    ap.add_argument("--only", nargs="+", choices=NAMES, help="run only these steps")
    ap.add_argument("--skip", nargs="+", choices=NAMES, default=[], help="skip these steps")
    a = ap.parse_args()

    steps = STEPS
    if a.start:
        steps = steps[NAMES.index(a.start):]
    if a.only:
        steps = [s for s in steps if s[0] in a.only]
    steps = [s for s in steps if s[0] not in a.skip]

    city = get_city(a.city)
    print(f"GeoSense setup: {city.name} ({city.region_label}) — {len(steps)} step(s)")
    results = []
    for name, cmd, optional in steps:
        t = time.time()
        print(f"\n[{name}]")
        code = run(name, cmd, city.id)
        took = time.time() - t
        results.append((name, code, took))
        if code != 0 and not optional:
            print(f"\nStopped at '{name}' (exit {code}). Fix it, then resume with:  "
                  f"python scripts/setup_city.py --city {city.id} --from {name}")
            break
        if code != 0:
            print(f"  '{name}' did not complete (exit {code}); continuing — that layer stays marked unavailable.")
    print("\nSummary")
    for name, code, took in results:
        print(f"  {name:<11} {'ok' if code == 0 else f'exit {code}'}  ({took:,.0f} s)")
    return 0 if all(c == 0 or dict((s[0], s[2]) for s in STEPS)[n] for n, c, _ in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
