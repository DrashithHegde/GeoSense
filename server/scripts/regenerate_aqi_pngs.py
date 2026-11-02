import sys
from pathlib import Path
SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT))

from app.services.surfaces.aqi_surface import generate_aqi_surface
import json

if __name__ == "__main__":
    report = generate_aqi_surface(start_date='2026-09-23', end_date='2026-10-07')
    print(json.dumps(report, indent=2))
