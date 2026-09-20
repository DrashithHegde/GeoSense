"""Quick import sanity check for the fixed import paths."""
import sys
from pathlib import Path

# Add server to path, simulating uvicorn running from server/ directory
SERVER_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SERVER_ROOT))

print("Testing imports after import path fix...")
print()

try:
    print("1. Testing app.main import...")
    from app.main import app
    print("   ✓ app.main imports successfully")
except Exception as e:
    print(f"   ✗ FAILED: {e}")
    sys.exit(1)

try:
    print("2. Testing app.api.routes import...")
    from app.api.routes import router
    print("   ✓ app.api.routes imports successfully")
except Exception as e:
    print(f"   ✗ FAILED: {e}")
    sys.exit(1)

try:
    print("3. Testing aqi_surface service import...")
    from app.services.surfaces.aqi_surface import generate_aqi_surface
    print("   ✓ aqi_surface imports successfully")
except Exception as e:
    print(f"   ✗ FAILED: {e}")
    sys.exit(1)

try:
    print("4. Testing openaq.derive_aqi_grid import (from aqi_surface)...")
    from openaq.derive_aqi_grid import idw_estimate
    print("   ✓ openaq.derive_aqi_grid imports successfully")
except Exception as e:
    print(f"   ✗ FAILED: {e}")
    sys.exit(1)

try:
    print("5. Testing scheduler imports...")
    from openaq.derive_aqi_grid import collect_station_aqi_points
    from gee.ingest_lst import COMPOSITE_WINDOW_DAYS as LST_WINDOW
    from gee.ingest_ndvi_ndwi import COMPOSITE_WINDOW_DAYS as S2_WINDOW
    print("   ✓ scheduler dependencies import successfully")
except Exception as e:
    print(f"   ✗ FAILED: {e}")
    sys.exit(1)

try:
    print("6. Testing aqicn imports...")
    from aqicn.ingest_aqicn import parse_aqicn_time
    print("   ✓ aqicn modules import successfully")
except Exception as e:
    print(f"   ✗ FAILED: {e}")
    sys.exit(1)

print()
print("=" * 60)
print("✓ ALL IMPORTS SUCCESSFUL")
print("=" * 60)
print()
print("The FastAPI backend should now start successfully using:")
print("  cd server")
print(r"  ..\.venv\Scripts\uvicorn.exe app.main:app --reload")
