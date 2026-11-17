"""Fetch real OpenAQ v3 CPCB-network station data, compute CPCB AQI, and build the IDW AQI
surface for one city.

Requires OPENAQ_AQI_KEY in the repo-root .env and internet access to api.openaq.org.

    python scripts/generate_aqi_station_surface.py [--city mumbai|delhi|bengaluru]

The cells get their AQI from this surface when the ML pipeline runs (run_ml_pipeline.py), and
the map panel reads it live, so there is no separate per-cell AQI step.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT))

from app.services.surfaces.aqi_station_surface import build_aqi_surface  # noqa: E402
from openaq.derive_aqi_grid import collect_station_aqi_points  # noqa: E402


def _has_generated_layer() -> bool:
    from app.services.surfaces.aqi_station_surface import MANIFEST_PATH
    try:
        rec = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["surfaces"].get("aqi") or {}
    except Exception:
        return False
    return rec.get("generation_status") == "generated"


def main() -> int:
    from app.services.surfaces.aqi_station_surface import MIN_STATIONS, eligible_stations
    try:
        points, fetched, failures = collect_station_aqi_points(max_age_hours=48.0)
    except RuntimeError as exc:
        if _has_generated_layer():
            # a failed run never replaces a good layer (it is hidden by itself once it is > 48 h old)
            print(json.dumps({"status": "kept_previous", "reason": str(exc)}, indent=2))
            return 2
        # no layer yet: record an honest 'insufficient coverage' state for the frontend
        record = build_aqi_surface([])
        record["audit"]["openaq_error"] = str(exc)
        print(json.dumps({"status": record["generation_status"], "reason": str(exc)}, indent=2))
        return 2

    fresh, _ = eligible_stations(points)
    if len(fresh) < MIN_STATIONS and _has_generated_layer():
        print(json.dumps({"status": "kept_previous",
                          "reason": f"only {len(fresh)} fresh station(s) this time (need {MIN_STATIONS})"}, indent=2))
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
    return 0


if __name__ == "__main__":
    from app.core.cities import run_script_for_city  # noqa: E402
    raise SystemExit(run_script_for_city(main))
