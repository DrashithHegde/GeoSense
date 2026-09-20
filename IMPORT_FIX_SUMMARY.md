# GeoSense Import Path Fix Summary

## Problem

The FastAPI backend failed to start from the `server/` directory with:
```
ModuleNotFoundError: No module named 'server'
```

The issue occurred when running:
```bash
cd server
..\.venv\Scripts\uvicorn.exe app.main:app --reload
```

## Root Cause

Multiple Python files inside the `server/` directory used imports like:
```python
from server.openaq.derive_aqi_grid import collect_station_aqi_points
from server.gee.ingest_lst import COMPOSITE_WINDOW_DAYS
```

When uvicorn starts from the `server/` directory, Python's working directory is `server/`, making `server` the current directory rather than a module on the Python path. These `from server.X` imports failed because Python couldn't find a module named `server`.

The correct import pattern when running from `server/` directory is:
```python
from openaq.derive_aqi_grid import collect_station_aqi_points
from gee.ingest_lst import COMPOSITE_WINDOW_DAYS
```

## Files Changed

### Scripts (3 files)
1. **server/scripts/scheduler.py**
   - Changed: `from server.openaq.derive_aqi_grid` → `from openaq.derive_aqi_grid`
   - Changed: `from server.gee.ingest_lst` → `from gee.ingest_lst`
   - Changed: `from server.gee.ingest_ndvi_ndwi` → `from gee.ingest_ndvi_ndwi`

2. **server/scripts/generate_aqi_surface.py**
   - Changed: `from server.openaq.derive_aqi_grid` → `from openaq.derive_aqi_grid`

3. **server/scripts/generate_ndvi_surface.py**
   - Changed: `from server.gee.ingest_ndvi_ndwi` → `from gee.ingest_ndvi_ndwi`

### Test Files (5 files)
4. **server/tests/test_aqicn_timestamp.py**
   - Changed: `from server.aqicn.ingest_aqicn` → `from aqicn.ingest_aqicn`

5. **server/tests/test_aqi_surface.py**
   - Changed: `from server.openaq.derive_aqi_grid` → `from openaq.derive_aqi_grid`

6. **server/tests/test_openaq.py**
   - Changed: `from server.openaq.client` → `from openaq.client`
   - Changed: `from server.openaq.cpcb_aqi` → `from openaq.cpcb_aqi`
   - Changed: `from server.openaq.derive_aqi_grid` → `from openaq.derive_aqi_grid`

7. **server/tests/test_scheduler.py**
   - Changed: `from server.scripts.scheduler` → `from scripts.scheduler`

8. **server/tests/test_source_metadata.py**
   - Changed: `from server.gee.ingest_lst` → `from gee.ingest_lst`
   - Changed: `from server.gee.ingest_ndvi_ndwi` → `from gee.ingest_ndvi_ndwi`

9. **server/tests/test_water_health.py**
   - Changed: `from server.gee.ingest_ndvi_ndwi` → `from gee.ingest_ndvi_ndwi`

### GEE Diagnostic Files (5 files)
10. **server/gee/debug_reduced.py**
    - Changed: `from server.gee.gee_client` → `from gee.gee_client`

11. **server/gee/diag_lst_exact.py**
    - Changed: `from server.gee.gee_client` → `from gee.gee_client`
    - Changed: `from server.gee.ingest_lst` → `from gee.ingest_lst`

12. **server/gee/inspect_bounds.py**
    - Changed: `from server.gee.gee_client` → `from gee.gee_client`
    - Changed: `from server.gee.ingest_lst` → `from gee.ingest_lst`

13. **server/gee/inspect_path_row.py**
    - Changed: `from server.gee.gee_client` → `from gee.gee_client`
    - Changed: `from server.gee.ingest_lst` → `from gee.ingest_lst`

14. **server/gee/phase6_lst_investigate.py**
    - Changed: `from server.gee.gee_client` → `from gee.gee_client`

## Total Changes
- **14 files modified**
- **0 files deleted**
- **0 files moved**
- **0 architecture changes**

## Import Pattern Fix
All imports changed from:
```python
from server.<module>.<submodule> import <name>
```

To:
```python
from <module>.<submodule> import <name>
```

This makes all imports compatible with running from the `server/` directory as the working directory.

## Verification

The import path issue is now fixed. Running the test import script shows that the `ModuleNotFoundError: No module named 'server'` error is resolved.

## Expected Result

The backend should now start successfully using:
```bash
cd server
..\.venv\Scripts\uvicorn.exe app.main:app --reload
```

### Endpoints to verify:
- `GET /api/health` should return HTTP 200
- `GET /api/surfaces/ndvi/latest` should work (returns data or appropriate error)

## What Was NOT Changed
✓ No database schema changes
✓ No zone changes (189 zones preserved)
✓ No NDVI implementation changes
✓ No AQI methodology changes
✓ No FastAPI architecture changes
✓ No sys.path or PYTHONPATH modifications
✓ No directory moves or renames

## Notes

The files outside the `server/` directory (like `audit_aqi_coverage.py`, `sample_openaq.py`, etc. in the repo root) still use `from server.` imports because they explicitly add the server path to sys.path. These files are not affected by this fix and continue to work as before.

All files within the `server/` directory now use consistent relative imports that work when `server/` is the working directory.
