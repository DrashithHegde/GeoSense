# Import Fix Verification Checklist

## Quick Verification Steps

### 1. Start the FastAPI Backend
```bash
cd server
..\.venv\Scripts\uvicorn.exe app.main:app --reload
```

**Expected:**
- No `ModuleNotFoundError: No module named 'server'` error
- FastAPI starts and shows startup logs
- Server listening on http://127.0.0.1:8000

### 2. Test Health Endpoint
```bash
curl http://127.0.0.1:8000/api/health
```

**Expected:**
- HTTP 200 response
- JSON response with status information

### 3. Test NDVI Surface Endpoint
```bash
curl http://127.0.0.1:8000/api/surfaces/ndvi/latest
```

**Expected:**
- HTTP 200 response with surface data, OR
- HTTP 404 with appropriate error message if no surface exists

### 4. Run Test Suite
```bash
cd server
python -m pytest -v
```

**Expected:**
- 76+ tests pass
- No import errors related to `server` module
- Warnings are acceptable

### 5. Test Scheduler Script (Dry Run)
```bash
cd server
python scripts/scheduler.py --dry-run
```

**Expected:**
- Prints schedule information
- No import errors
- Exits cleanly

### 6. Test Import of Key Modules
```bash
cd server
python -c "from openaq.derive_aqi_grid import collect_station_aqi_points; print('✓ openaq imports')"
python -c "from gee.ingest_lst import run_ingest; print('✓ gee.ingest_lst imports')"
python -c "from aqicn.ingest_aqicn import parse_aqicn_time; print('✓ aqicn imports')"
python -c "from app.services.surfaces.aqi_surface import generate_aqi_surface; print('✓ aqi_surface imports')"
```

**Expected:**
- All commands print success messages
- No `ModuleNotFoundError: No module named 'server'` errors

## If Issues Occur

### Missing Dependencies Error
If you see errors like:
```
ModuleNotFoundError: No module named 'geoalchemy2'
```

**Solution:** Install dependencies
```bash
cd server
..\.venv\Scripts\pip.exe install -r requirements.txt
```

### Database Connection Error
If you see database connection errors:

**Check:**
1. PostgreSQL is running
2. `.env` file exists in `server/` with correct credentials
3. Database `geosense` exists

### Different Import Error
If you see a different import error (not related to `server` module):

**Action:**
1. Check the full error traceback
2. Verify the module/file exists
3. Check if it's a dependency issue vs. import path issue

## Success Criteria

✓ FastAPI starts without `ModuleNotFoundError: No module named 'server'`
✓ `/api/health` returns HTTP 200
✓ Tests run without import errors
✓ No regression in existing functionality

## What to Report

When verifying, report:
1. Exact command used to start the backend
2. Any errors encountered (full traceback)
3. HTTP status codes for health and NDVI endpoints
4. Test results (passed/failed count)
