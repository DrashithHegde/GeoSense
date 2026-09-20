"""Generate the current static AQI surface from real canonical OpenAQ inputs.

This does not write to PostgreSQL and never creates synthetic stations.  The
normal scheduler invokes the same service after a successful AQI grid cycle.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

SERVER_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVER_ROOT.parent
for path in (str(REPO_ROOT), str(SERVER_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from app.services.surfaces.aqi_surface import AqiSurfaceConfig, generate_aqi_surface
from openaq.derive_aqi_grid import collect_station_aqi_points


def main() -> int:
    stations, _fetched, _failures = collect_station_aqi_points()
    report = generate_aqi_surface(
        stations,
        source_timestamp=max(station["observed_at"] for station in stations),
        config=AqiSurfaceConfig(),
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
