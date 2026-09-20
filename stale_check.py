import sys, pathlib, requests, json
from datetime import datetime, timezone
sys.path.insert(0, str(pathlib.Path(r"C:\Users\DRASHITH HEGDE\OneDrive\Desktop\GeoSense\server")))
from app.core.config import get_settings
from server.openaq.client import discover_mmr_stations, OPENAQ_BASE, _headers

api_key = get_settings().openaq_aqi_key

# Check the actual API timestamp vs local time to detect timezone confusion
now_utc = datetime.now(timezone.utc)
print(f"Local UTC now: {now_utc.isoformat()}")

# Fetch metadata for a few active stations - check latestMeasurements field
stations = discover_mmr_stations(api_key)
# Take the first 3 known-active CPCB stations
active_ids = [6945, 6967, 3409322]  # Kurla, Sion, Pimpleshwar Thane

print("\n=== OPENAQ LOCATION METADATA (lastUpdated / datetimeLast fields) ===")
for loc_id in active_ids:
    resp = requests.get(f"{OPENAQ_BASE}/locations/{loc_id}", 
                        headers=_headers(api_key), timeout=15)
    if resp.status_code != 200:
        print(f"  {loc_id}: HTTP {resp.status_code}")
        continue
    loc = resp.json()["results"][0]
    print(f"\n  Station {loc_id}: {loc.get('name')}")
    print(f"    datetimeLast: {loc.get('datetimeLast')}")
    print(f"    datetimeFirst: {loc.get('datetimeFirst')}")

    # Also get the actual latest measurements
    resp2 = requests.get(f"{OPENAQ_BASE}/locations/{loc_id}/latest",
                         headers=_headers(api_key), timeout=15)
    meas = resp2.json().get("results", [])
    if meas:
        times = [m.get("datetime", {}) for m in meas if m.get("datetime")]
        utc_times = [t.get("utc") for t in times if t.get("utc")]
        if utc_times:
            latest_utc = max(utc_times)
            age_h = (now_utc - datetime.fromisoformat(latest_utc.replace("Z", "+00:00"))).total_seconds() / 3600
            print(f"    Latest measurement UTC: {latest_utc}")
            print(f"    Age from now: {age_h:.1f} hours")
