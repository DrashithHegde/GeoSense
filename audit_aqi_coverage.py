import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(r'C:\Users\DRASHITH HEGDE\OneDrive\Desktop\GeoSense\server')))
from server.openaq.client import discover_mmr_stations, fetch_latest_measurements, _parse_utc_dt, _build_sensor_map, AQI_POLLUTANTS, CO_PPB_TO_UGM3
from server.openaq.cpcb_aqi import compute_station_cpcb_aqi
from server.openaq.derive_aqi_grid import freshness_label
from server.aqicn.derive_aqi_grid import haversine_m
from app.core.config import get_settings
from datetime import datetime, timezone
import json

api_key = get_settings().openaq_aqi_key
stations = discover_mmr_stations(api_key)

print(f"Total discovered stations: {len(stations)}")

CENTROIDS = {
    "Mumbai": (19.0760, 72.8777),
    "Mira-Bhayandar": (19.2952, 72.8544),
    "Thane": (19.2183, 72.9781)
}

report_lines = []
usable_stations = []

for s in stations:
    loc_id = s["id"]
    try:
        raw = fetch_latest_measurements(api_key, loc_id)
    except:
        continue
    
    sensors_meta = _build_sensor_map(s.get("sensors", []))
    pollutants = {}
    timestamps = []
    
    has_pm25, has_pm10, has_no2, has_so2, has_o3, has_co = False, False, False, False, False, False
    
    for meas in raw:
        sensor_id = meas.get("sensorsId")
        val = meas.get("value")
        dt_obj = meas.get("datetime")
        if sensor_id is None or val is None: continue
        
        info = sensors_meta.get(int(sensor_id), {})
        param = info.get("param_name", "").lower()
        units = info.get("units", "").lower()
        
        if param not in AQI_POLLUTANTS: continue
        
        obs_at = _parse_utc_dt(dt_obj)
        if obs_at is None: continue
        
        v = float(val)
        if param == "co" and "ppb" in units:
            v *= CO_PPB_TO_UGM3
            
        if "\u00b5g/m" in units or "ug/m" in units:
            pollutants[param] = v
            timestamps.append(obs_at)
        elif param not in pollutants and param != "co":
            pollutants[param] = v
            timestamps.append(obs_at)
            
        if param == "pm25": has_pm25 = True
        if param == "pm10": has_pm10 = True
        if param == "no2": has_no2 = True
        if param == "so2": has_so2 = True
        if param == "o3": has_o3 = True
        if param == "co": has_co = True
        
    latest_obs = max(timestamps) if timestamps else None
    age_h = (datetime.now(timezone.utc) - latest_obs).total_seconds() / 3600 if latest_obs else -1
    freshness = freshness_label(latest_obs) if latest_obs else "none"
    
    aqi, dom, sub = compute_station_cpcb_aqi(pollutants) if pollutants else (None, None, {})
    
    dist_m = haversine_m(s["latitude"], s["longitude"], CENTROIDS["Mumbai"][0], CENTROIDS["Mumbai"][1])
    dist_mb = haversine_m(s["latitude"], s["longitude"], CENTROIDS["Mira-Bhayandar"][0], CENTROIDS["Mira-Bhayandar"][1])
    dist_t = haversine_m(s["latitude"], s["longitude"], CENTROIDS["Thane"][0], CENTROIDS["Thane"][1])
    
    is_usable = (aqi is not None and age_h <= 48.0)  # we'll flag negative age (future) later
    if is_usable:
        usable_stations.append({
            "id": s["id"], "name": s["name"], "lat": s["latitude"], "lon": s["longitude"],
            "aqi": aqi, "d_m": dist_m, "d_mb": dist_mb, "d_t": dist_t
        })
        
    pol_str = f"PM2.5:{int(has_pm25)} PM10:{int(has_pm10)} NO2:{int(has_no2)} SO2:{int(has_so2)} O3:{int(has_o3)} CO:{int(has_co)}"
    
    report_lines.append(f"{s['id']:>8} | {s['name'][:25]:<25} | {s['provider'][:10]:<10} | {pol_str} | {age_h:>5.1f}h | AQI:{str(aqi):<4} Usable:{is_usable}")

print("\n--- STATION REPORT ---")
for r in report_lines:
    print(r)

print("\n--- MUNICIPALITY COVERAGE (Approximate based on Centroids) ---")
for muni, m_lat, m_lon in [("Mumbai", CENTROIDS["Mumbai"][0], CENTROIDS["Mumbai"][1]), 
                           ("Mira-Bhayandar", CENTROIDS["Mira-Bhayandar"][0], CENTROIDS["Mira-Bhayandar"][1]),
                           ("Thane", CENTROIDS["Thane"][0], CENTROIDS["Thane"][1])]:
    c_5k = sum(1 for us in usable_stations if haversine_m(us["lat"], us["lon"], m_lat, m_lon) <= 5000)
    c_10k = sum(1 for us in usable_stations if haversine_m(us["lat"], us["lon"], m_lat, m_lon) <= 10000)
    c_20k = sum(1 for us in usable_stations if haversine_m(us["lat"], us["lon"], m_lat, m_lon) <= 20000)
    print(f"{muni:<15} | <=5km: {c_5k:<2} | <=10km: {c_10k:<2} | <=20km: {c_20k:<2}")

