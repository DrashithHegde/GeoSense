# NDVI Source Creation Failure - Root Cause Analysis

## Executive Summary

**FINDING: The NDVI Mapbox source is never created because of a RACE CONDITION between style loading and data availability.**

## Two Code Paths for NDVI Source Creation

### Path 1: setupLayers() - Initial Style Load
**Location:** `client/src/hooks/index.js` Line 415-417

```javascript
if (ndviSurfaceRef.current && !map.getSource(NDVI_SURFACE_SOURCE)) {
  map.addSource(NDVI_SURFACE_SOURCE, { type: "image", url: getApiUrl(ndviSurfaceRef.current.image_url), coordinates: ndviSurfaceRef.current.coordinates });
}
```

**Triggered by:** `map.on("style.load", setupLayers)` (Line 458)

**When it runs:**
- Mapbox map is created in the main useEffect (dependency: `[containerRef]`)
- This useEffect runs ONCE when component mounts
- `setupLayers()` is attached as listener to `"style.load"` event
- The style loads shortly after map creation
- At this time, `ndviSurfaceRef.current` is likely **NULL** because:
  - Mumbai has just been selected
  - useGeoSenseData useEffect triggers
  - fetchData() is called
  - But the async fetch hasn't completed yet

**Result:** NDVI source is NOT created because `ndviSurfaceRef.current === null`

### Path 2: NDVI useEffect - Data Arrives
**Location:** `client/src/hooks/index.js` Line 191-234

```javascript
useEffect(() => {
  ndviSurfaceRef.current = ndviSurface;
  const map = mapRef.current;
  if (!map || !map.isStyleLoaded() || !ndviSurface) return;  // ← LINE 194
  
  // ... diagnostic logging ...
  
  const imageOptions = { url: getApiUrl(ndviSurface.image_url), coordinates: ndviSurface.coordinates };
  const sync = () => {
    const source = map.getSource(NDVI_SURFACE_SOURCE);
    if (source) source.updateImage(imageOptions);
    else map.addSource(NDVI_SURFACE_SOURCE, { type: "image", ...imageOptions });
    if (!map.getLayer(NDVI_SURFACE_LAYER)) {
      map.addLayer({
        id: NDVI_SURFACE_LAYER, type: "raster", source: NDVI_SURFACE_SOURCE,
        layout: { visibility: "none" }, paint: { "raster-opacity": 0.9, "raster-fade-duration": 0 }
      },
        map.getLayer(MUNI_EXTRUDE) ? MUNI_EXTRUDE : undefined);
    }
    applyMunicipalityPaint(map, activeLayersRef.current, selectedMuniRef.current, !!aqiSurfaceRef.current, true);
  };
  if (map.isStyleLoaded()) sync(); else map.once("idle", sync);  // ← LINE 234
}, [ndviSurface]);
```

**Triggered by:** Changes to `ndviSurface` state (dependency: `[ndviSurface]`)

**When it runs:**
- AFTER the async fetch completes
- AFTER `setNdviSurface(data)` is called
- React re-renders and this useEffect fires

**Critical Check at Line 194:**
```javascript
if (!map || !map.isStyleLoaded() || !ndviSurface) return;
```

## The Race Condition

### Scenario A: Style Loads BEFORE Data (LIKELY)
1. Map created → style loads → `setupLayers()` runs
2. At this time: `ndviSurfaceRef.current === null`
3. NDVI source NOT created in setupLayers
4. Later: NDVI data fetched → `setNdviSurface(data)`
5. NDVI useEffect fires → checks `map.isStyleLoaded()`
6. **IF `map.isStyleLoaded() === FALSE`**: early return at line 194
7. **NDVI source NEVER created**

### Scenario B: Multiple Style Reloads
1. If Mapbox style reloads (due to network errors, style switching, etc.)
2. During reload: `map.isStyleLoaded() === false`
3. If NDVI data arrives during this window
4. NDVI useEffect early returns
5. **NDVI source NEVER created**

### Scenario C: "idle" Event Never Fires
Line 234: `if (map.isStyleLoaded()) sync(); else map.once("idle", sync);`

- If `map.isStyleLoaded()` returns `false`
- Code waits for `"idle"` event
- **If the map NEVER becomes idle** (due to continuous errors, tile loading failures, etc.)
- **The `sync()` function NEVER executes**
- **NDVI source NEVER created**

## Evidence from User's Report

1. ✅ **ndviSurface = true** → Data arrived successfully
2. ✅ **hasNdviSurface = true** → State is correct
3. ✅ **isNdviSurfaceMode = true** → Logic is correct
4. ❌ **map.getSource(NDVI_SURFACE_SOURCE) = false** → Source not created
5. ❌ **map.getLayer(NDVI_SURFACE_LAYER) = false** → Layer not created
6. ⚠️ **Many failed Mapbox vector tile requests** → Style may be unstable

## Root Cause

**The user reported "many failed Mapbox vector tile requests".**

This suggests:
- The Mapbox style is repeatedly failing to load tiles
- `map.isStyleLoaded()` may be returning `false` OR
- The map may never reach "idle" state due to continuous errors OR
- The style is reloading repeatedly, clearing any sources/layers added

## Why This Doesn't Affect AQI Surface

Looking at the AQI surface useEffect (Line 164-187), it has the SAME pattern:

```javascript
useEffect(() => {
  aqiSurfaceRef.current = aqiSurface;
  const map = mapRef.current;
  if (!map || !map.isStyleLoaded() || !aqiSurface) return;  // ← SAME CHECK
  // ...
  if (map.isStyleLoaded()) sync(); else map.once("idle", sync);  // ← SAME PATTERN
}, [aqiSurface]);
```

**If AQI surface IS visible but NDVI is NOT:**
- AQI data may arrive BEFORE the Mapbox issues begin
- Or AQI data arrives when `map.isStyleLoaded() === true`
- But by the time NDVI data arrives, the map is in an error state

## Hypothesis for Next Investigation

The failed Mapbox vector tile requests are the key:

### Question 1: What is failing?
The user mentioned "failed Mapbox vector tile requests" - these are likely:
- `https://api.mapbox.com/v4/...` (legacy tile API - deprecated)
- Returning 401 Unauthorized OR 403 Forbidden
- Due to token issues, account limits, or deprecated API usage

### Question 2: Does this block style loading?
- If the basemap style tries to load these tiles and fails
- `map.isStyleLoaded()` may return `false` indefinitely
- Or the map continuously retries, never reaching "idle"

### Question 3: Why does the app appear to work otherwise?
- The map may render partially (base tiles, geometries work)
- But the style is technically not "fully loaded"
- So `map.isStyleLoaded()` returns `false`
- Blocking the NDVI useEffect from proceeding

## Verification Needed

To confirm this hypothesis, we need to log:

1. **In the NDVI useEffect (Line 194):**
   ```javascript
   console.log("NDVI useEffect fired");
   console.log("  map exists:", !!map);
   console.log("  map.isStyleLoaded():", map?.isStyleLoaded());
   console.log("  ndviSurface exists:", !!ndviSurface);
   ```

2. **After the early return:**
   If `map.isStyleLoaded() === false`, log:
   ```javascript
   console.warn("NDVI useEffect blocked - style not loaded");
   console.warn("  Will wait for 'idle' event");
   ```

3. **In the sync() function:**
   ```javascript
   console.log("NDVI sync() executing - about to create source");
   ```

4. **After map.addSource:**
   ```javascript
   console.log("NDVI source created successfully");
   console.log("  Verification:", !!map.getSource(NDVI_SURFACE_SOURCE));
   ```

5. **Listen for Mapbox events:**
   ```javascript
   map.on("idle", () => console.log("Map idle event fired"));
   map.on("style.load", () => console.log("Style load event fired"));
   ```

## Expected Findings

If the hypothesis is correct, we'll see:

```
NDVI useEffect fired
  map exists: true
  map.isStyleLoaded(): false  ← BLOCKED HERE
  ndviSurface exists: true

NDVI useEffect blocked - style not loaded
  Will wait for 'idle' event

(time passes...)

(NO "Map idle event fired" log - map never becomes idle)
(NO "NDVI sync() executing" log - sync never runs)
```

## Conclusion

**The NDVI source is not created because:**

1. `setupLayers()` runs BEFORE NDVI data arrives (too early)
2. NDVI useEffect runs AFTER data arrives BUT:
   - `map.isStyleLoaded()` returns `false` (due to tile loading errors)
   - OR map never reaches "idle" state (due to continuous retry errors)
3. The `sync()` function that creates the source NEVER executes

**The fix will depend on the map's actual state:**
- If `map.isStyleLoaded()` is truly `false`: we need to handle partial style loading
- If the map never reaches "idle": we need a different trigger or timeout
- If there are Mapbox errors blocking the lifecycle: we need to fix the token/style configuration

**DO NOT implement a fix yet - confirm the hypothesis first with targeted logging.**
