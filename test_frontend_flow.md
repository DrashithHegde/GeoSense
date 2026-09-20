# Frontend NDVI Data Flow Analysis

## Current Understanding

### Data Flow Path

1. **useGeoSenseData Hook** (`client/src/hooks/useGeoSenseData.js`)
   - useEffect triggers when `activeCity` changes (dependency: `[activeCity]`)
   - Line 25: Only fetches for Mumbai: `if (activeCity !== "mumbai") { ... return; }`
   - Line 45: Calls `fetchData()` async function
   - Line 51-60: Fetches NDVI with diagnostic: `🔍 [NDVI FETCH START]`
   - Line 73-78: Logs response: `📡 [NDVI FETCH RESPONSE]`
   - Line 88-120: Parses JSON: `📦 [NDVI FETCH DATA PARSING]`
   - Line 186-193: Assigns to state: `💾 [NDVI STATE ASSIGNMENT]` → `setNdviSurface(ndviSurfaceData)`
   - Line 217: Returns `{ ..., ndviSurface, ... }`

2. **App Component** (`client/src/App.jsx`)
   - Line 76: Calls hook: `const { ..., ndviSurface, ... } = useGeoSenseData(activeCity);`
   - Line 83-89: Passes to useMapbox:
     ```javascript
     useMapbox({
       containerRef: mapContainerRef,
       activeCity,
       activeLayers,
       onZoneClick: handleZoneClick,
       liveMunicipalities,
       waterBodies,
       aqiSurface,
       ndviSurface,  // ← passed here
       boundary: liveBoundary,
     });
     ```

3. **useMapbox Hook** (`client/src/hooks/index.js`)
   - Line 118: Receives parameter: `ndviSurface = null`
   - Line 122-127: Logs reception: `[GEOSENSE DIAGNOSTICS] useMapbox hook called`
   - Line 135: Creates ref: `const ndviSurfaceRef = useRef(ndviSurface);`
   - Line 166-221: useEffect with dependency `[ndviSurface]`
     - Line 167: Updates ref: `ndviSurfaceRef.current = ndviSurface;`
     - Line 168: Early return if: `!map || !map.isStyleLoaded() || !ndviSurface`
     - Line 171-192: Logs NDVI data received: `🌿 NDVI SURFACE DATA RECEIVED`
     - Line 194-207: Creates/updates Mapbox source and layer
     - Line 208: Calls `applyMunicipalityPaint()` with `hasNdviSurface=true`

4. **applyMunicipalityPaint Function** (`client/src/hooks/index.js`)
   - Line 519: Receives: `hasNdviSurface = false` (default)
   - Line 522: Calculates: `isNdviSurfaceMode = layerId === "ndvi" && hasNdviSurface`
   - Line 528-569: Runtime diagnostic: `🔍 NDVI RUNTIME DIAGNOSTIC`
   - Line 571-573: Sets visibility: `isNdviSurfaceMode ? "visible" : "none"`

## Critical Analysis

### Issue Identified: Timing and Dependency

**The Problem:**
- `useGeoSenseData` has dependency `[activeCity]` (line 217)
- This means NDVI is fetched when Mumbai is **first selected**
- NDVI layer button click does NOT trigger a re-fetch
- User must select Mumbai first, THEN click NDVI

### Verification Needed

**What happens in this sequence:**

1. User starts at India overview (`activeCity = null`)
2. User selects Mumbai → triggers `useGeoSenseData` useEffect
3. `fetchData()` runs → fetches NDVI from backend
4. `setNdviSurface(ndviSurfaceData)` sets state
5. React re-renders App component
6. App passes `ndviSurface` prop to `useMapbox`
7. `useMapbox` useEffect with dependency `[ndviSurface]` triggers
8. NDVI source/layer created in Mapbox
9. User clicks NDVI layer button
10. `activeLayers.ndvi` becomes `true`
11. `applyMunicipalityPaint` called with `hasNdviSurface` boolean
12. Visibility set based on `isNdviSurfaceMode = layerId === "ndvi" && hasNdviSurface`

### Potential Failure Points

**A. State not persisting**
- `ndviSurface` set to `null` after fetch completes
- React state update race condition

**B. Ref not syncing**
- Line 167: `ndviSurfaceRef.current = ndviSurface;` not executing
- Ref holds stale `null` value

**C. useEffect not triggering**
- Line 166: `useEffect(..., [ndviSurface])` doesn't fire when state changes
- Common if `ndviSurface` object reference doesn't change

**D. Early return preventing layer creation**
- Line 168: `if (!ndviSurface) return;` blocks execution
- Layer never created in Mapbox

**E. Visibility calculation wrong**
- Line 522: `hasNdviSurface` passed as `false` despite data existing
- Line 573: Visibility stays `"none"`

## Expected Diagnostic Output

When user selects Mumbai, console should show:

```
🔄 [useGeoSenseData useEffect TRIGGERED]
  activeCity: mumbai
  Will fetch NDVI? true

🔎 [FETCH FUNCTION CALLED]
  activeCity: mumbai
  About to fetch all Mumbai data including NDVI

🔍 [NDVI FETCH START]
  Exact URL: http://localhost:8000/api/surfaces/ndvi/latest
  Timestamp: ...

📡 [NDVI FETCH RESPONSE]
  HTTP Status: 200
  response.ok: true
  Content-Type: application/json

📦 [NDVI FETCH DATA PARSING]
  ndviSurfaceRes.ok: true
  ✅ JSON parse successful
  [NDVI FETCH DATA] Complete response: {metric, image_url, coordinates, ...}
  Has image_url: true
  Has coordinates: true
  Has metric: true

💾 [NDVI STATE ASSIGNMENT]
  About to call setNdviSurface with: {...}
  Is null? false
  Is undefined? false
  Truthy? true

[GEOSENSE DIAGNOSTICS] useMapbox hook called
  activeCity: mumbai
  activeLayers: {aqi: true, ndvi: false, ...}
  aqiSurface: true
  ndviSurface: true  ← MUST be true here

🌿 NDVI SURFACE DATA RECEIVED
  4. ndviSurface data: {metric, image_url, coordinates, ...}
  9. Exact NDVI image URL: http://localhost:8000/surface-assets/ndvi/...
  10. Browser fetch status for NDVI image: 200 OK
```

When user clicks NDVI button:

```
🔍 NDVI RUNTIME DIAGNOSTIC
  1. activeLayers: {aqi: false, ndvi: true, ...}
  2. getPrimaryLayerId(activeLayers): "ndvi"
  3. hasNdviSurface: true  ← MUST be true here
  4. isNdviSurfaceMode: true  ← MUST be true here
  5. map.getSource(NDVI_SURFACE_SOURCE) exists: true
  6. map.getLayer(NDVI_SURFACE_LAYER) exists: true
  7. NDVI layer visibility: "visible"  ← MUST be "visible"
  8. NDVI raster opacity: 0.9
```

## Next Steps

Since user cannot collect browser logs, we need to:

1. **Verify backend PNG is accessible**
   - Test: `http://localhost:8000/surface-assets/ndvi/ndvi_20260913T000000Z.png`
   - Should return valid PNG file

2. **Check if frontend container can reach backend**
   - Network connectivity between Docker containers
   - CORS headers on backend

3. **Simplify to identify exact failure**
   - Add more granular diagnostics
   - Or: manually inspect React DevTools state
   - Or: add a test button that logs current state

## Hypothesis

**Most Likely:** `ndviSurface` state is `null` when it should contain data.

**Possible causes:**
- Fetch failing silently (200 response but invalid JSON)
- State update not triggering re-render
- Component unmounting before state sets
- `activeCity` changing during fetch (race condition)

**Evidence needed:**
- What is `ndviSurface` value immediately after `setNdviSurface()` call?
- Does `useMapbox` useEffect fire with `ndviSurface` data?
- What is `ndviSurfaceRef.current` value in `applyMunicipalityPaint`?
