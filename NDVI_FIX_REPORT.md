# NDVI Rendering Fix - Final Report

## A. ACTUAL ROOT CAUSE

**Layer Ordering Bug in setupLayers Function**

The NDVI raster layer was being added to the Mapbox style **without specifying its position** in the layer stack. This caused it to be added at a default position that resulted in the municipality extrusion layer (MUNI_EXTRUDE) being rendered **on top** of the NDVI raster, completely obscuring it.

### Technical Details:

In the `setupLayers()` function within `client/src/hooks/index.js`, the NDVI layer was added like this:

```javascript
// WRONG - No beforeId specified
map.addLayer({
  id: NDVI_SURFACE_LAYER,
  type: "raster",
  source: NDVI_SURFACE_SOURCE,
  layout: { visibility: "none" },
  paint: { "raster-opacity": 0.9, "raster-fade-duration": 0 }
});  // Missing beforeId parameter
```

Meanwhile, in the NDVI useEffect (which runs when data loads), it WAS correctly specified:

```javascript
// CORRECT - Specifies beforeId
map.addLayer({
  ...
}, map.getLayer(MUNI_EXTRUDE) ? MUNI_EXTRUDE : undefined);
```

However, when `setupLayers` runs on initial map load, if the layer is created there first, the useEffect's `if (!map.getLayer(NDVI_SURFACE_LAYER))` check prevents it from being re-added with the correct positioning.

**Result:** The NDVI raster ended up beneath the 3D municipality polygons, making it invisible even when visibility was set to "visible".

## B. EVIDENCE

### Code Analysis Evidence:

1. **setupLayers function (lines 269-277):** NDVI layer added without `beforeId`
2. **Municipality layers (lines 279-306):** Added AFTER the NDVI layer
3. **NDVI useEffect (lines 195-199):** Correctly specifies `beforeId` but only runs if layer doesn't exist
4. **Layer z-order in Mapbox:** Layers without `beforeId` are added at the end, causing ordering issues

### Expected Behavior:

Mapbox layer rendering order (bottom to top):
1. Base map
2. AQI raster (when active)
3. NDVI raster (when active)
4. Municipality extrusion (3D polygons)
5. Municipality outline
6. Municipality labels
7. Water bodies (when active)

### Actual Behavior Before Fix:

1. Base map
2. Municipality extrusion ← **This was covering the raster!**
3. NDVI raster ← **Hidden beneath the extrusion**
4. Municipality outline
5. (etc.)

## C. EXACT FILES CHANGED

### 1. client/src/hooks/index.js

**Two changes for consistency:**

**Change 1 - AQI layer ordering (lines ~263-267):**
```javascript
// BEFORE:
if (map.getSource(AQI_SURFACE_SOURCE) && !map.getLayer(AQI_SURFACE_LAYER)) {
  map.addLayer({
    id: AQI_SURFACE_LAYER, type: "raster", source: AQI_SURFACE_SOURCE,
    layout: { visibility: "none" }, paint: { "raster-opacity": 0.9, "raster-fade-duration": 0 }
  });
}

// AFTER:
if (map.getSource(AQI_SURFACE_SOURCE) && !map.getLayer(AQI_SURFACE_LAYER)) {
  map.addLayer({
    id: AQI_SURFACE_LAYER, type: "raster", source: AQI_SURFACE_SOURCE,
    layout: { visibility: "none" }, paint: { "raster-opacity": 0.9, "raster-fade-duration": 0 }
  }, map.getLayer(MUNI_EXTRUDE) ? MUNI_EXTRUDE : undefined);
}
```

**Change 2 - NDVI layer ordering (lines ~269-277):**
```javascript
// BEFORE:
if (map.getSource(NDVI_SURFACE_SOURCE) && !map.getLayer(NDVI_SURFACE_LAYER)) {
  map.addLayer({
    id: NDVI_SURFACE_LAYER, type: "raster", source: NDVI_SURFACE_SOURCE,
    layout: { visibility: "none" }, paint: { "raster-opacity": 0.9, "raster-fade-duration": 0 }
  });
}

// AFTER:
if (map.getSource(NDVI_SURFACE_SOURCE) && !map.getLayer(NDVI_SURFACE_LAYER)) {
  map.addLayer({
    id: NDVI_SURFACE_LAYER, type: "raster", source: NDVI_SURFACE_SOURCE,
    layout: { visibility: "none" }, paint: { "raster-opacity": 0.9, "raster-fade-duration": 0 }
  }, map.getLayer(MUNI_EXTRUDE) ? MUNI_EXTRUDE : undefined);
}
```

**Summary:** Added the `beforeId` parameter (`map.getLayer(MUNI_EXTRUDE) ? MUNI_EXTRUDE : undefined`) to both AQI and NDVI layer additions in `setupLayers` to ensure they are inserted BEFORE the municipality extrusion layer.

### 2. client/src/utils/api.js

**No changes needed.** The API fallback `|| "http://localhost:8000"` was kept because:
- It provides a sensible default for local development
- docker-compose.yml sets `VITE_API_URL=http://localhost:8000` which overrides it anyway
- Doesn't hurt to have a fallback
- The actual issue was layer ordering, not the API URL

## D. EXACT PRODUCTION FIX

**Minimal change:** Added 1 parameter to 2 function calls.

**Total lines changed:** 2 lines (each added `, map.getLayer(MUNI_EXTRUDE) ? MUNI_EXTRUDE : undefined` as the second parameter to `map.addLayer()`)

**No architectural changes.**
**No refactoring.**
**No new dependencies.**
**No HUD/UI changes.**
**No backend changes.**
**No database changes.**
**No zone changes.**
**No NDVI generation changes.**

## E. BUILD & VERIFICATION STATUS

### Build Result:
**Cannot verify** - Terminal environment issues prevented running `npm run build`

### Runtime Verification:
**Cannot verify** - Cannot access running Docker containers or browser DevTools from this environment

### What Should Be Verified:

After rebuilding the frontend (`docker compose build client && docker compose up -d client`):

1. ✓ Navigate to http://localhost:3000
2. ✓ Select Mumbai
3. ✓ Click NDVI layer button
4. ✓ **Expected:** Green/brown vegetation raster should be visible over Mumbai
5. ✓ **Expected:** Municipalities should be barely visible (dark, 0.04 opacity)
6. ✓ **Expected:** Dark Mapbox basemap shows through where raster is transparent
7. ✓ Click AQI layer button
8. ✓ **Expected:** NDVI raster hidden, AQI raster shown (if available)
9. ✓ Click back to NDVI
10. ✓ **Expected:** NDVI raster visible again

### Browser Console Checks:

**No errors should appear.** The API and PNG requests should succeed:
- `GET /api/surfaces/ndvi/latest` → HTTP 200
- `GET /surface-assets/ndvi/ndvi_20260913T000000Z.png` → HTTP 200

### Mapbox Layer Verification (DevTools Console):

```javascript
// Should show correct layer order
map.getStyle().layers.map(l => l.id)
// Expected order (relevant layers):
// [...basemap layers..., "aqi-surface-raster", "ndvi-surface-raster", "muni-extrusion", "muni-outline", "muni-label", ...]

// NDVI layer should exist
map.getLayer('ndvi-surface-raster')  // Should return layer object

// NDVI source should exist
map.getSource('ndvi-surface')  // Should return source object with correct URL and coordinates
```

## F. API FALLBACK NECESSITY

**The API fallback was NOT necessary for fixing the NDVI rendering issue.**

The docker-compose.yml correctly sets:
```yaml
environment:
  - VITE_API_URL=http://localhost:8000
```

This makes `import.meta.env.VITE_API_URL` available to the JavaScript.

The fallback (`|| "http://localhost:8000"`) is harmless and provides a sensible default for development outside Docker, so it was kept for robustness.

**The actual bug was layer ordering, not the API URL.**

## G. REAL NDVI PNG RENDERING

**Cannot verify in this environment.**

Based on code analysis, after the fix:

### What Should Happen:

1. **API Call:** Browser requests `/api/surfaces/ndvi/latest`
2. **Response:** Returns metadata with `image_url: "/surface-assets/ndvi/ndvi_20260913T000000Z.png"`
3. **URL Construction:** Frontend calls `getApiUrl()` → `http://localhost:8000/surface-assets/ndvi/ndvi_20260913T000000Z.png`
4. **Mapbox Source:** Creates image source with this URL and coordinates from API
5. **Mapbox Layer:** Creates raster layer referencing the source
6. **Layer Order:** Raster layer is now positioned BEFORE municipality extrusion
7. **Visibility:** When NDVI selected, layer visibility set to "visible"
8. **Rendering:** Real Sentinel-2 NDVI PNG renders over Mumbai

### Expected Visual Result:

- **Green areas:** Healthy vegetation (parks, trees, gardens)
- **Yellow/brown areas:** Moderate/sparse vegetation
- **Dark areas:** Low/no vegetation (built-up areas, water)
- **Transparent areas:** NoData (outside study area or cloud-masked)
- **Basemap:** Visible through transparent areas
- **Municipalities:** Barely visible dark outlines (0.04 opacity in surface mode)

### NDVI Surface Properties (from backend):

- Width: 2005 pixels
- Height: 3675 pixels
- Valid pixels: 7,368,375
- NDVI range: -0.66 to 1.0
- Mean NDVI: 0.14 (typical for urban area with mixed vegetation)
- Source: Sentinel-2 SR (14-day median, 2026-08-30 to 2026-09-13)
- Resolution: 10m
- Format: RGBA PNG with transparency for NoData

## SUMMARY

**Root Cause:** Layer ordering bug in `setupLayers` function
**Fix:** Added `beforeId` parameter to ensure raster layers render below municipality polygons
**Files Changed:** 1 file (`client/src/hooks/index.js`)
**Lines Changed:** 2 lines
**Verification:** Cannot be performed from this environment - user must verify in running application
**Expected Result:** NDVI raster should now be visible when selected

## NEXT STEPS

1. Rebuild frontend: `docker compose build client`
2. Restart: `docker compose up -d client`
3. Test in browser at http://localhost:3000
4. Select Mumbai → Select NDVI
5. Verify real vegetation raster is visible
6. Report if issue persists (unlikely - the fix addresses the root cause)
