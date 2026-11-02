import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(r'C:\Users\DRASHITH HEGDE\OneDrive\Desktop\GeoSense\server')))
from server.openaq.client import get_mumbai_station_measurements
from server.openaq.cpcb_aqi import compute_station_cpcb_aqi
from app.core.config import get_settings

api_key = get_settings().openaq_aqi_key
stations = get_mumbai_station_measurements(api_key, max_age_hours=48.0, cpcb_only=True)

for s in stations[:5]:
    aqi, dominant, sub_indices = compute_station_cpcb_aqi(s['pollutants'])
    print(f"Station: {s['station_id']} - {s['station_name']}")
    print(f"Timestamp: {s['observed_at']}")
    print(f"Raw Pollutants: {s['pollutants']}")
    print(f"Sub-Indices: {sub_indices}")
    print(f"Dominant: {dominant}")
    print(f"Final AQI: {aqi}")
    print('-'*40)
