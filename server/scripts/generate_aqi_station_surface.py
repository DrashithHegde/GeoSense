"""Fetch real OpenAQ v3 CPCB/MPCB station data, compute CPCB AQI, and build the
IDW AQI surface (+ optionally write per-cell AQI into environment_data).

Requires OPENAQ_AQI_KEY in the repo-root .env and internet access to api.openaq.org.

    python scripts/generate_aqi_station_surface.py            # surface only
    python scripts/generate_aqi_station_surface.py --cells    # surface + 300 m cells
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT))

from app.services.surfaces.aqi_station_surface import MIN_STATIONS, build_aqi_surface  # noqa: E402
from openaq.derive_aqi_grid import collect_station_aqi_points, run_openaq_derivation  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", action="store_true", help="also IDW AQI into spatial_cells (environment_data)")
    args = ap.parse_args()

    try:
        points, fetched, failures = collect_station_aqi_points(max_age_hours=48.0)
    except RuntimeError as exc:
        # Still record an honest 'insufficient coverage' state for the frontend.
        record = build_aqi_surface([])
        record["audit"]["openaq_error"] = str(exc)
        print(json.dumps({"status": record["generation_status"], "reason": str(exc)}, indent=2))
        return 2

    record = build_aqi_surface(points)
    print(json.dumps({
        "status": record["generation_status"],
        "stations_fetched": fetched,
        "cpcb_aqi_failures": failures,
        "stations_eligible": record["audit"]["stations_eligible"],
        "reason": record.get("reason"),
        "aqi_range": [record.get("aqi_min"), record.get("aqi_max")],
    }, indent=2, default=str))

    if args.cells and record["generation_status"] == "generated":
        summary = run_openaq_derivation(min_stations=MIN_STATIONS - 1, station_points=points,
                                        stations_fetched=fetched, cpcb_aqi_failures=failures)
        print(json.dumps({k: summary[k] for k in ("zones_total", "zones_observed", "zones_estimated",
                                                  "zones_uncovered", "coverage_percent")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
