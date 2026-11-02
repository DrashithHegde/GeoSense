# Backend NDVI Endpoint Diagnostic Instructions

## Problem

The endpoint `/api/surfaces/ndvi/latest` hangs indefinitely (stays on "loading" in browser).

## Diagnostics Added

Added comprehensive logging to:
1. **FastAPI endpoint** (`server/app/api/routes.py` line 191)
2. **Loader function** (`server/app/services/surfaces/ndvi_surface.py` line 248)

## Test Procedure

### 1. Restart the Backend Server

The logging won't appear until the server restarts to load the new code.

```bash
docker compose restart server
```

Or if running directly:
```bash
# Stop current server (Ctrl+C)
# Start again
cd server
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. Watch Backend Logs

Open a terminal and watch the server output:
```bash
docker compose logs -f server
```

### 3. Test Simple Endpoint First

Verify FastAPI is responsive:

**In browser, open:**
```
http://localhost:8000/api/health
```

**Expected:**
```json
{"status":"healthy","phase":"2","version":"2.0.0"}
```

**If this hangs:** FastAPI/Uvicorn itself is not responding properly.

### 4. Test NDVI Endpoint

**In browser, open:**
```
http://localhost:8000/api/surfaces/ndvi/latest
```

**Watch the backend logs** for these messages:
```
[NDVI API ENTER] /api/surfaces/ndvi/latest endpoint called
[NDVI API] About to call load_latest_ndvi_surface()
[NDVI LOADER] load_latest_ndvi_surface called
[NDVI LOADER] manifest_path: /path/to/manifest.json
[NDVI LOADER] Reading manifest file
[NDVI LOADER] Manifest loaded, checking for ndvi surface
[NDVI LOADER] NDVI record found: True/False
[NDVI LOADER] generation_status: generated/pending/error
[NDVI LOADER] Returning: True/False
[NDVI API] load_latest_ndvi_surface returned: True/False
[NDVI API] Building response object
[NDVI API RETURN] Returning response
```

### 5. Identify Where It Hangs

**If you see:**
- `[NDVI API ENTER]` but nothing after → Hangs immediately on entry
- `[NDVI API] About to call...` but no `[NDVI LOADER]` → Hangs on function call
- `[NDVI LOADER]` starts but stops at a specific step → That's where it hangs
- All logs appear but browser still loading → Response not reaching client
- No logs at all → Endpoint not being called / routing issue

## Possible Issues

### A. Manifest File Issue
**Symptoms:** Hangs at "Reading manifest file"

**Causes:**
- Manifest file is very large
- File permissions issue
- Disk I/O problem

**Check:**
```bash
ls -lh server/data/surfaces/manifest.json
cat server/data/surfaces/manifest.json
```

### B. Import/Module Issue
**Symptoms:** No logs appear at all

**Causes:**
- Import error preventing module load
- Function not actually imported
- Route not registered

**Check backend startup logs for import errors**

### C. Async/Await Issue
**Symptoms:** Endpoint called but hangs with no subsequent logs

**Causes:**
- Blocking operation in async function
- Deadlock
- Event loop issue

**Note:** The endpoint is `async` but `load_latest_ndvi_surface` is synchronous

### D. Path Resolution Issue
**Symptoms:** Hangs at manifest path check

**Causes:**
- `Path(__file__)` resolving incorrectly in Docker
- Symlink issues
- Mount point problems

### E. JSON Parsing Issue
**Symptoms:** Hangs at "Reading manifest file"

**Causes:**
- Extremely large JSON file
- Invalid JSON syntax causing parser to hang
- Encoding issues

## Expected Behavior

The endpoint should:
1. Read `server/data/surfaces/manifest.json` (should be fast)
2. Parse JSON (should be fast)
3. Extract `surfaces.ndvi` record
4. Validate `generation_status == "generated"`
5. Return response (should be immediate)

**Total time:** < 100ms

## Next Steps

After collecting the backend logs:

1. Report which log message is the LAST one you see
2. Report if the browser eventually times out or stays loading forever
3. Check if the manifest.json file exists and is readable
4. Check the file size of manifest.json
5. Try opening manifest.json in a text editor to verify it's valid JSON

This will pinpoint the exact line where the hang occurs.
