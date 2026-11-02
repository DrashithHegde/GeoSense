# NDVI Fetch Investigation - Execution Path Analysis

## Current Status

**Problem:** `ndviSurface` state is `false`, causing NDVI raster not to render.

**Known Facts:**
1. ✅ NDVI layer selection works (`activeLayers.ndvi = true`)
2. ✅ NDVI PNG file exists and is valid (11.31 MB, 100% opaque pixels)
3. ✅ NDVI GeoTIFF exists and is valid (7.3M pixels, correct bounds)
4. ❌ `ndviSurface` state is `false` in React
5. ❌ Mapbox source/layer don't exist (cannot be created without data)

## Data Flow Architecture

**File:** `client/src/hooks/useGeoSenseData.js`

**useEffect dependency:** `[activeCity]`

### Execution Timing

```
User opens page
  └─> activeCity = null
  └─> useEffect does NOT run (activeCity !== "mumbai")

User selects Mumbai
  └─> activeCity = "mumbai"  ← DEPENDENCY CHANGES
  └─> useEffect RUNS
      └─> fetchData() called
          └─> Promise.all([
                fetch("/api/metrics/latest"),
                fetch("/api/anomalies"),
                fetch("/api/zones/boundary"),
                fetch("/api/municipalities/latest"),
                fetch("/api/water-bodies/latest"),
                fetch("/api/surfaces/aqi/latest"),
                fetch("/api/surfaces/ndvi/latest"),  ← NDVI FETCHED HERE
              ])
          └─> setNdviSurface(ndviSurfaceData)

User clicks NDVI layer
  └─> activeLayers.ndvi = true  ← STATE CHANGES
  └─> useEffect does NOT run (activeCity unchanged)
  └─> No new fetch happens
  └─> Uses existing ndviSurface state from Mumbai selection
```

**Critical Point:** NDVI data is fetched when **Mumbai is selected**, not when **NDVI layer is clicked**.

## Added Diagnostics

### 1. useEffect Trigger (Line 20-28)
```javascript
console.log("🔄 [useGeoSenseData useEffect TRIGGERED]");
console.log("  activeCity:", activeCity);
console.log("  Will fetch NDVI?", activeCity === "mumbai");
```
**When it logs:** Every time `activeCity` changes

### 2. Fetch Function Called (Line 45-50)
```javascript
console.log("🔎 [FETCH FUNCTION CALLED]");
console.log("  activeCity:", activeCity);
console.log("  About to fetch all Mumbai data including NDVI");
```
**When it logs:** When `fetchData()` is invoked

### 3. NDVI Fetch Start (Line 56-60)
```javascript
console.log("🔍 [NDVI FETCH START]");
console.log("  Exact URL:", ndviUrl);
console.log("  Timestamp:", new Date().toISOString());
```
**When it logs:** Before the NDVI fetch request

### 4. NDVI Fetch Response (Line 73-78)
```javascript
console.log("📡 [NDVI FETCH RESPONSE]");
console.log("  HTTP Status:", ndviSurfaceRes.status);
console.log("  response.ok:", ndviSurfaceRes.ok);
console.log("  Content-Type:", ndviSurfaceRes.headers.get('Content-Type'));
```
**When it logs:** After the NDVI fetch completes

### 5. NDVI Data Parsing (Line 88-120)
```javascript
console.log("📦 [NDVI FETCH DATA PARSING]");
console.log("  ndviSurfaceRes.ok:", ndviSurfaceRes.ok);
// ... detailed parsing logic
```
**When it logs:** During JSON parsing

### 6. NDVI State Assignment (Line 186-193)
```javascript
console.log("💾 [NDVI STATE ASSIGNMENT]");
console.log("  About to call setNdviSurface with:", ndviSurfaceData);
```
**When it logs:** Before calling `setNdviSurface()`

### 7. NDVI Fetch Error (Line 200-207)
```javascript
console.error("❌ [NDVI FETCH ERROR]");
console.error("  Error message:", err.message);
```
**When it logs:** If any error occurs during fetch

## Investigation Steps

### Step 1: Verify Diagnostics Are Active

1. Hard refresh browser (Ctrl+Shift+R)
2. Clear console
3. Navigate to India overview (home page)
4. **Select Mumbai** ← THIS triggers the fetch
5. Look for these logs in order:
   ```
   🔄 [useGeoSenseData useEffect TRIGGERED]
   🔎 [FETCH FUNCTION CALLED]
   🔍 [NDVI FETCH START]
   📡 [NDVI FETCH RESPONSE]
   📦 [NDVI FETCH DATA PARSING]
   💾 [NDVI STATE ASSIGNMENT]
   ```

### Step 2: Test Backend Endpoint Directly

Run the Python test script:
```bash
python test_ndvi_endpoint.py
```

Expected output:
```
HTTP Status: 200
Response body:
{
  "metric": "ndvi",
  "image_url": "/surface-assets/ndvi/ndvi_20260913T000000Z.png",
  "coordinates": [[72.77,19.22],[72.95,19.22],[72.95,18.89],[72.77,18.89]],
  "generated_at": "...",
  ...
}
```

### Step 3: Compare Backend vs Frontend

**If backend returns 200 with valid data:**
- Check if frontend sees the same response
- Check if JSON parsing succeeds
- Check if `setNdviSurface()` is called with correct data
- Check if state update succeeds

**If backend returns 404/500:**
- Backend endpoint is broken
- NDVI surface hasn't been generated
- Check backend logs for errors

**If backend connection fails:**
- Backend container not running
- Port 8000 not accessible
- Network/firewall issue

## Possible Root Causes

### A. NDVI fetch runs and returns 200 with valid data
- ✅ Backend working
- ✅ Frontend receives data
- ❌ State assignment fails or gets reset

### B. NDVI fetch runs but returns 404/500
- ❌ Backend endpoint broken
- ❌ NDVI surface not generated
- Check: Backend logs, surface files

### C. NDVI fetch runs but has network/CORS error
- ❌ Cannot reach backend
- ❌ CORS policy blocking
- Check: Browser network tab, backend CORS config

### D. NDVI fetch returns 200 but JSON parsing fails
- ❌ Invalid JSON response
- ❌ Unexpected response format
- Check: Response Content-Type, response body

### E. NDVI fetch returns valid JSON but `setNdviSurface()` not called
- ❌ Logic error before state assignment
- ❌ Conditional branch preventing assignment
- Check: Logs show parsing but not assignment

### F. `setNdviSurface()` called but state becomes false/null afterward
- ❌ Another effect resetting state
- ❌ State update race condition
- Check: Multiple useEffect logs, state overwrites

### G. NDVI branch never reached at all
- ❌ `fetchData()` never called
- ❌ Function exits early
- Check: No logs at all from fetch diagnostics

## Next Steps

**DO NOT make any code changes until:**

1. We confirm which logs appear when Mumbai is selected
2. We verify the backend endpoint response
3. We identify the exact failure point in the data flow

**After identifying the root cause, we can:**
- Fix the backend endpoint (if 404/500)
- Fix the frontend parsing (if JSON error)
- Fix the state management (if assignment fails)
- Fix the dependency array (if fetch timing is wrong)

But first: **Run the diagnostics and report ALL console output from Mumbai selection.**
