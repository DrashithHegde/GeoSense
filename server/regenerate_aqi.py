import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.abspath("server"))
from gee.gee_client import initialize_ee
from app.services.surfaces.aqi_surface import generate_aqi_surface
from gee.ingest_aqi import run_ingest

def regenerate():
    print("Ingesting AQI to database...")
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=14)
    start_str = start.isoformat()
    end_str = end.isoformat()
    
    try:
        report = run_ingest(start_date=start_str, end_date=end_str)
        print("Ingest complete:", report)
    except Exception as e:
        print("Ingest error:", e)

    print("Generating AQI Surface...")
    try:
        record = generate_aqi_surface(start_date=start_str, end_date=end_str)
        print("Regeneration complete!")
        print(record)
    except Exception as e:
        print("Surface generation error:", e)

if __name__ == "__main__":
    regenerate()
