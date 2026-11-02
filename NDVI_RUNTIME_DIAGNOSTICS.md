# NDVI Runtime Diagnostics Added

## Changes Made

Added comprehensive console logging to `client/src/hooks/index.js` to diagnose NDVI rendering at runtime.

## What Will Be Logged

### When NDVI Surface Data Is Received (on useEffect)

**Console group:** `🌿 NDVI SURFACE DATA RECEIVED`

Logs:
- **4. ndviSurface data:** The complete NDVI surface object received from API
  - metric
  - image_url (relative path)
  - coordinates (Mapbox format)
  - generated_at
  - nodata flag
- **9. Exact NDVI image URL:** The full constructed URL (e.g., `http://localhost:8000/surface-assets/...`)
- **10. Browser fetch status:** HTTP HEAD request result
  - Status code (200, 404, etc.)
  - Content-Type header
  - Content-Length header
  - Or error if fetch fails

### When NDVI Is Selected (in applyMunicipalityPaint)

**Console group:** `🔍 NDVI RUNTIME DIAGNOSTIC`

Logs:
- **1. activeLayers:** Complete activeLayers state object
- **2. getPrimaryLayerId(activeLayers):** Result of layer ID calculation
- **3. hasNdviSurface:** Boolean passed to function
- **4. isNdviSurfaceMode:** Computed boolean (layerId === "ndvi" && hasNdviSurface)
- **5. map.getSource(NDVI_SURFACE_SOURCE) exists:** Boolean + source details if exists
  - Source type
  - Source URL (from serialization)
  - Source coordinates
- **6. map.getLayer(NDVI_SURFACE_LAYER) exists:** Boolean + layer details if exists
  - Layer type
  - Layer source reference
- **7. NDVI layer visibility:** Current visibility property value
- **8. NDVI raster opacity:** Current raster-opacity paint property value
- **Layer stack positions:**
  - NDVI_SURFACE_LAYER index in layer stack
  - MUNI_EXTRUDE index in layer stack
  - Whether NDVI is before MUNI (correct ordering)

### Mapbox Events (continuous monitoring)

**11. Mapbox error events:**
- Any Mapbox `map.on("error")` events
- Error message
- Source ID if applicable

**NDVI source loading events:**
- `✅ NDVI source data loaded successfully` - when source finishes loading
- `📡 NDVI sourcedata event` - with details:
  - isSourceLoaded
  - dataType
  - tile info

### React Cleanup (on component unmount)

**12. React cleanup diagnostics:**
- Whether NDVI layer exists before cleanup
- Whether NDVI source exists before cleanup

## How to Test

1. Rebuild and restart the frontend Docker container:
   ```bash
   docker compose build client
   docker compose up -d client
   ```

2. Open browser to `http://localhost:3000`

3. Open browser DevTools console (F12)

4. Select Mumbai city

5. Click the NDVI layer toggle

6. Observe console output with all diagnostic information

## Expected Output Order

```
🌿 NDVI SURFACE DATA RECEIVED
  4. ndviSurface data: {...}
  9. Exact NDVI image URL: http://localhost:8000/...
  10. Browser fetch status: 200 OK
  
📡 NDVI sourcedata event: {...}

✅ NDVI source data loaded successfully

🔍 NDVI RUNTIME DIAGNOSTIC
  1. activeLayers: {...}
  2. getPrimaryLayerId(activeLayers): "ndvi"
  3. hasNdviSurface: true
  4. isNdviSurfaceMode: true
  5. map.getSource(...) exists: true
  6. map.getLayer(...) exists: true
  7. NDVI layer visibility: "visible"
  8. NDVI raster opacity: 0.9
  Layer stack positions:
    - NDVI_SURFACE_LAYER at index: X
    - MUNI_EXTRUDE at index: Y
    - Layer order (NDVI before MUNI?): true
```

## Cleanup

After collecting diagnostic output, remove these temporary logs by searching for:
```
TEMPORARY.*DIAGNOSTIC
```

And delete all marked sections.

## Files Modified

- `client/src/hooks/index.js` - Added diagnostic logging only (no logic changes)
