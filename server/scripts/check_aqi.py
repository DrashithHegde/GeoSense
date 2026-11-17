"""Check the current AQI layer: how fresh each station is and which pollutants it reported.

    python scripts/check_aqi.py [--city mumbai|delhi|bengaluru]

Reads the AQI surface the map is using (data/surfaces/manifest.json) — no server needed.
Freshness policy (openaq/derive_aqi_grid.py): fresh < 6 h · stale 6-48 h (used, labelled) · > 48 h rejected.
CPCB AQI needs at least 3 pollutants including PM2.5 or PM10 (CPCB 2014 method).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT))

from app.core.cities import city_path, run_script_for_city  # noqa: E402

MANIFEST = city_path("surfaces", "manifest.json")
POLLUTANTS = ["pm25", "pm10", "no2", "so2", "o3", "co", "nh3"]
LABEL = {"pm25": "PM2.5", "pm10": "PM10", "no2": "NO2", "so2": "SO2", "o3": "O3", "co": "CO", "nh3": "NH3"}


def _age_h(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 3600.0


def main() -> int:
    if not MANIFEST.exists():
        print("No surface manifest yet - run setup.ps1 first.")
        return 1
    aqi = (json.loads(MANIFEST.read_text(encoding="utf-8")).get("surfaces") or {}).get("aqi")
    if not aqi:
        print("No AQI surface in the manifest. Generate it: python scripts/generate_aqi_station_surface.py")
        return 1
    stations = aqi.get("stations") or []
    built = _age_h(aqi.get("generated_at"))
    print(f"AQI layer status: {aqi.get('generation_status')} · built {aqi.get('generated_at')}"
          + (f" ({built:.1f} h ago)" if built is not None else ""))
    print(f"Stations used: {len(stations)}\n")
    head = f"{'Station':38s} {'AQI':>4s} {'Main':6s} {'Age now':>8s}  {'Fresh?':11s} " + " ".join(f"{LABEL[p]:>5s}" for p in POLLUTANTS)
    print(head)
    print("-" * len(head))
    counts = {p: 0 for p in POLLUTANTS}
    ages = []
    for s in sorted(stations, key=lambda x: x.get("station_name") or ""):
        subs = s.get("sub_indices") or {}
        subs = {str(k).lower().replace(".", "").replace("₂", "2").replace("₃", "3"): v for k, v in subs.items()}
        age = _age_h(s.get("observed_at"))
        ages.append(age)
        state = "rejected" if age is not None and age > 48 else ("fresh" if age is not None and age < 6 else "stale")
        cells = []
        for p in POLLUTANTS:
            ok = subs.get(p) is not None
            counts[p] += ok
            cells.append(f"{'yes' if ok else '-':>5s}")
        print(f"{(s.get('station_name') or '?')[:38]:38s} {str(s.get('aqi') or '-'):>4s} "
              f"{str(s.get('dominant_pollutant') or '-')[:6]:6s} "
              f"{(f'{age:.1f} h' if age is not None else '?'):>8s}  {state:11s} " + " ".join(cells))
    n = len(stations) or 1
    good = [a for a in ages if a is not None]
    print("\nPollutant coverage: " + " · ".join(f"{LABEL[p]} {counts[p]}/{len(stations)}" for p in POLLUTANTS))
    if good:
        print(f"Reading age right now: newest {min(good):.1f} h · median {sorted(good)[len(good)//2]:.1f} h · oldest {max(good):.1f} h")
        old = sum(1 for a in good if a > 48)
        if old:
            print(f"! {old} station(s) are now older than 48 h - regenerate the AQI layer "
                  "(python scripts/generate_aqi_station_surface.py) to refresh it.")
    print("\nThese are the 7 CPCB AQI pollutants available in real time. Lead (Pb), the 8th, is sampled manually "
          "with about a week's lag, so CPCB also leaves it out of the real-time AQI.")
    return 0


if __name__ == "__main__":
    sys.exit(run_script_for_city(main))
