import requests
import psycopg2
from datetime import datetime
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

# Mumbai AQI stations from AQICN
MUMBAI_STATIONS = {
    'Borivali East': 'mumbai-borivali-east',
    'Kurla': 'mumbai-kurla',
    'Deonar': 'mumbai-deonar',
    'Colaba': 'mumbai-colaba',
    'Andheri': 'mumbai-andheri',
    'Bhandup': 'mumbai-bhandup',
    'Malad': 'mumbai-malad',
    'Navi Mumbai': 'navi-mumbai'
}

# Station coordinates (lat, lon) for matching to localities
STATION_COORDS = {
    'Borivali East': (19.230, 72.860),
    'Kurla': (19.075, 72.885),
    'Deonar': (19.042, 72.882),
    'Colaba': (18.906, 72.814),
    'Andheri': (19.119, 72.847),
    'Bhandup': (19.152, 72.935),
    'Malad': (19.186, 72.848),
    'Navi Mumbai': (19.033, 73.020)
}

def fetch_aqi_data(api_token):
    """Fetch real-time AQI from all Mumbai stations"""
    results = []
    
    for station_name, coords in STATION_COORDS.items():
        lat, lon = coords
        # Use exact geographic coordinates to find the nearest station
        url = f"https://api.waqi.info/feed/geo:{lat};{lon}/"
        params = {'token': api_token}
        
        try:
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            if data.get('status') == 'ok':
                iaqi = data['data'].get('iaqi', {})
                results.append({
                    'station_name': station_name,
                    'latitude': lat,
                    'longitude': lon,
                    'aqi': data['data'].get('aqi'),
                    'pm25': iaqi.get('pm25', {}).get('v'),
                    'pm10': iaqi.get('pm10', {}).get('v'),
                    'no2': iaqi.get('no2', {}).get('v'),
                    'o3': iaqi.get('o3', {}).get('v'),
                    'so2': iaqi.get('so2', {}).get('v'),
                    'co': iaqi.get('co', {}).get('v'),
                    'temperature': iaqi.get('t', {}).get('v'),
                    'humidity': iaqi.get('h', {}).get('v'),
                    'timestamp': datetime.now()
                })
                print(f"✅ Fetched AQI for {station_name}: {data['data'].get('aqi')} (nearest station: {data['data'].get('city', {}).get('name')})")
            else:
                print(f"⚠️ Failed for {station_name}: {data.get('data')}")
                
        except Exception as e:
            print(f"❌ Error fetching {station_name}: {e}")
    
    return results

def store_aqi_to_db(aqi_data):
    """Store AQI data in PostgreSQL"""
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        database=os.getenv("DB_NAME", "geosense"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres")
    )
    cur = conn.cursor()
    
    # First get locality_id for each station (nearest locality)
    for record in aqi_data:
        # Find nearest locality (simplified - you can implement proper spatial join)
        cur.execute("""
            SELECT id FROM localities 
            WHERE ST_DWithin(
                geometry, 
                ST_SetSRID(ST_MakePoint(%s, %s), 4326), 
                0.05
            )
            LIMIT 1
        """, (record['longitude'], record['latitude']))
        
        result = cur.fetchone()
        if result:
            locality_id = result[0]
            
            # Insert metrics
            cur.execute("""
                INSERT INTO environmental_metrics 
                (locality_id, date, aqi, pm25, pm10, no2, o3, so2, co, temperature, humidity)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                locality_id, record['timestamp'].date(),
                record['aqi'], record['pm25'], record['pm10'],
                record['no2'], record['o3'], record['so2'],
                record['co'], record['temperature'], record['humidity']
            ))
    
    conn.commit()
    cur.close()
    conn.close()
    print(f"✅ Stored {len(aqi_data)} AQI records to database")

if __name__ == "__main__":
    API_TOKEN = os.getenv("AQICN_TOKEN")
    if not API_TOKEN:
        print("❌ Please set AQICN_TOKEN environment variable")
    else:
        aqi_data = fetch_aqi_data(API_TOKEN)
        if aqi_data:
            store_aqi_to_db(aqi_data)
