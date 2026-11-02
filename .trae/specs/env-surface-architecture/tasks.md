# Environmental Surface Architecture: Implementation Tasks

Order: Dependency-safe vertical slices. P1 = highest priority.

---

## Task 1: BACKEND - Water Health Surface Service (mirrors ndvi_surface.py pattern)

**Priority**: high
**Status**: completed
**Maps AC**: AC-4.1, AC-4.2, FR-6

**Depends**: none (new file)

**Files**:
- CREATE: `server/app/services/surfaces/water_health_surface.py` ✅

**Work**: ✅ All implemented
- Surface service file exists at [water_health_surface.py](file:///c:/Users/DRASHITH%20HEGDE/OneDrive/Desktop/GeoSense/server/app/services/surfaces/water_health_surface.py)
- Constants: `SCALE_METERS=10`, `NODATA_VALUE=-9999.0`, `CRS=EPSG:4326`
- `build_water_health_composite()`: GEE Sentinel-2 pipeline with MNDWI≥0 mask, NDCI algal stress, turbidity proxy stress averaged
- `publish_water_health_geotiff()`: float32 GeoTIFF + RGBA PNG with water-semantic color ramp
  - Color stops: red 0.0 → orange 0.2 → yellow 0.4 → green 0.6 → teal 0.8 → blue/cyan 1.0 (healthy)
  - Alpha ramp: WH<0.05→transparent, WH≥0.5→alpha=210
- `load_latest_water_health_surface()`: reads manifest, filters generation_status==generated

**Test Requirements**:
- TR-1.1 (rule): ✅ File `server/app/services/surfaces/water_health_surface.py` exists (344 lines).
- TR-1.2 (rule): ✅ Manifest record structure in `publish_water_health_geotiff()` matches ndvi keys schema.
- TR-1.3 (rubric): ✅ Water-semantic color ramp (cyan healthy→red concern). Score: 2/2. Pass threshold ≥1.5.

**Completion Evidence**:
- `server/app/services/surfaces/water_health_surface.py` exists
- Sentinel-2 10m resolution confirmed
- NoData=-9999 for non-water pixels (never Water Health = 0)
- Color ramp matches water health semantics; not LST thermal scale reuse

---

## Task 2: BACKEND - Add Water Health Surface API Endpoints + Deep Analysis Pixel

**Priority**: high
**Status**: completed
**Maps AC**: AC-6.1, AC-6.2, AC-6.3, AC-7.1; FR-8, FR-10

**Depends**: Task 1

**Files**:
- MODIFY: `server/app/api/routes.py` ✅

**Work**: ✅ All implemented in [routes.py](file:///c:/Users/DRASHITH%20HEGDE/OneDrive/Desktop/GeoSense/server/app/api/routes.py)

### Part A: Surface Metadata Endpoint ✅
- `GET /api/surfaces/water-health/latest` (line 278-307) parallels NDVI pattern
- Returns metric, image_url, coordinates, generated_at, source_period, source_scale_m=10, nodata_semantics

### Part B: Pixel Value Endpoint ✅
- `GET /api/surfaces/water-health/value?lon=&lat=` (line 413-464)
- Uses rasterio Window(col,row,1,1) localized 1×1 read
- Non-water → nodata=true value=null
- Valid water → value rounded to 3 decimals
- Never reads colorized PNG; never substitutes cell average

### Part C: Deep Analysis pixel.water_health ✅
- `GET /api/analysis/point` (line 580-594) includes `pixel_water_health` block
- Calls `get_water_health_pixel_value()` endpoint internally
- Fields: value, nodata, source, resolution_m, source_period
- Distinct from `cell.metrics.water_health_score` (cell aggregate)

**Test Requirements**:
- TR-2.1 (rule): ✅ Endpoints defined; `py_compile server/app/api/routes.py` passes static check.
- TR-2.2 (rule): ✅ `pixel_block["water_health"]` key present with value/nodata/source/resolution_m subkeys.

**Completion Evidence**:
- `routes.py` line 278-307: `/surfaces/water-health/latest` endpoint
- `routes.py` line 413-464: `/surfaces/water-health/value` endpoint with 1×1 Window read
- `routes.py` line 580-602: pixel.water_health wired into analysis/point response

---

## Task 3: BACKEND - Script to Generate Water Health Surface Once

**Priority**: medium (required for runtime validation; BLOCKED if GEE unavailable)
**Status**: pending
**Maps AC**: AC-4.1

**Depends**: Task 1

**Files**:
- `server/scripts/generate_water_health_surface.py` (already exists)

**Work**:
- Run `py_compile` syntax check (already validated by glob)
- If GEE credentials + EE project are configured in the environment:
  - Run script to generate surface
  - Verify `server/data/surfaces/water-health/wh_*.tif` + `wh_*.png` created
  - Verify `manifest.json` receives `surfaces.water_health` with `generation_status=generated`
- If GEE not configured: record this limitation as evidence (code paths are correct statically)

**Test Requirements**:
- TR-3.1 (rule): Script passes `python -m py_compile`.
- TR-3.2 (rule): Conditional on GEE availability; if GEE blocked, explicit limitation recorded with rationale.

**Completion Evidence**: TBD after run attempt

---

## Task 4: FRONTEND - useGeoSenseData fetches Water Health surface metadata

**Priority**: high
**Status**: completed
**Maps AC**: AC-5.1, FR-11

**Depends**: Task 2

**Files**:
- MODIFY: `client/src/hooks/useGeoSenseData.js` ✅

**Work**: ✅ Already implemented in [useGeoSenseData.js](file:///c:/Users/DRASHITH%20HEGDE/OneDrive/Desktop/GeoSense/client/src/hooks/useGeoSenseData.js)
- State variable `waterHealthSurface` at line 17
- `fetchWaterHealthSurface()` helper at lines 58-69 with 404→null grace
- `Promise.all` includes `fetchWaterHealthSurface()` call at line 99
- State assignment at line 284: `setWaterHealthSurface(waterHealthSurfaceData)`
- Return destructuring at line 318 includes `waterHealthSurface`

**Test Requirements**:
- TR-4.1 (rule): ✅ Static audit confirms `waterHealthSurface` declared, set, returned.
- TR-4.2 (rule): ✅ Network request path `/api/surfaces/water-health/latest` exists.

**Completion Evidence**:
- Line 17: `const [waterHealthSurface, setWaterHealthSurface] = useState(null);`
- Line 99: in Promise.all
- Line 284: state assignment
- Line 318: returned in object

---

## Task 5: FRONTEND - App.jsx Prop Pass Fix + useMapbox Water Health consistency

**Priority**: highest (CRITICAL BUG blocks Water Health rendering)
**Status**: pending
**Maps AC**: AC-5.1, AC-5.2, AC-5.3, FR-9, FR-11

**Depends**: Task 4

**Files**:
- MODIFY: `client/src/App.jsx` (CRITICAL BUG FIX: destructure + pass waterHealthSurface)
- MODIFY: `client/src/hooks/index.js` (Water Health layer: layout visibility instead of raster-opacity)

**Work**:

### Part A: CRITICAL App.jsx Bug Fix
In [App.jsx](file:///c:/Users/DRASHITH%20HEGDE/OneDrive/Desktop/GeoSense/client/src/App.jsx) line 68, destructure `waterHealthSurface` from useGeoSenseData:
```js
const { zones: liveZones, liveMunicipalities, waterBodies, aqiSurface, ndviSurface, lstSurface, waterHealthSurface, boundary: liveBoundary, loading: zonesLoading, error: zonesError } = useGeoSenseData(activeCity);
```
And in the useMapbox call (lines 75-87), add prop:
```js
waterHealthSurface,
```

**Current bug**: `waterHealthSurface` is returned by useGeoSenseData but is NEVER destructured or passed, so the useMapbox hook always receives `waterHealthSurface = null` even when the backend has a generated surface.

### Part B: Water Health Layer consistency - use layout visibility not paint opacity
In [hooks/index.js](file:///c:/Users/DRASHITH%20HEGDE/OneDrive/Desktop/GeoSense/client/src/hooks/index.js):
1. `syncWaterHealth()` creates layer with `layout: { visibility: "none" }` (NOT `visible`), and paint `raster-opacity: 0.90` (NOT 0)
2. In `applyMunicipalityPaint()`, replace `setPaintProperty(..., "raster-opacity", ...)` with `setLayoutProperty(..., "visibility", isWaterHealthSurfaceMode ? "visible" : "none")` to match NDVI/LST/AQI pattern.

**Test Requirements**:
- TR-5.1 (rule): `App.jsx` destructures `waterHealthSurface` and passes it into `useMapbox()` call.
- TR-5.2 (rule): Water Health raster layer default `visibility: "none"`. Toggle uses `setLayoutProperty` not `setPaintProperty raster-opacity`.
- TR-5.3 (rule): `npm run build` passes.

**Completion Evidence**: TBD

---

## Task 6: FRONTEND - applyMunicipalityPaint signature + guard paths

**Priority**: highest
**Status**: completed
**Maps AC**: AC-1.1, AC-1.2, AC-5.2, FR-2, FR-9

**Depends**: Task 5 code structure compatible

**Files**:
- MODIFY: `client/src/hooks/index.js` ✅

**Work**: ✅ All guard paths implemented
- Signature at line 877: `applyMunicipalityPaint(..., hasWaterHealthSurface = false)` ✅
- `isWaterHealthSurfaceMode` at line 884 ✅
- `isSurfaceMode` includes WH at line 885 ✅
- `isEnvMetricPendingNoRasterYet` at lines 887-889 guarantees NDVI/water_health → `colorExpr = "#0e0e1a"` + opacity 0.06 even when raster not loaded ✅ → ensures NO old choropleth fallback ever appears
- WATER_FILL + WATER_OUTLINE `waterPolyVis` logic lines 1050-1076: set to `none` when `isWaterHealthSurfaceMode` true ✅

**Test Requirements**:
- TR-6.1 (rule): ✅ For `layerId==="ndvi"`, `isEnvMetricPendingNoRasterYet || isSurfaceMode → colorExpr="#0e0e1a"` always; old choropleth unreachable.
- TR-6.2 (rule): ✅ `isWaterHealthSurfaceMode → waterPolyVis="none"`
- TR-6.3 (rule): ✅ `isNdviSurfaceMode → opacityExpr=0.08 ≤0.12`
- TR-6.4 (rule): ✅ Signature has 7th param `hasWaterHealthSurface=false`

**Completion Evidence**:
- hooks/index.js line 877-1076: static audit of all branches
- NDVI old choropleth cannot render even when `hasNdviSurface=false`

---

## Task 7: FRONTEND - Deep Analysis Panel: pixel-level Water Health

**Priority**: medium
**Status**: completed
**Maps AC**: AC-7.1 presentation

**Depends**: Task 2

**Files**:
- MODIFY: `client/src/components/panels/DeepAnalysisOverlay.jsx` ✅

**Work**: ✅ Already implemented
- Line 126: `pixelWaterHealth` extracted from `pixel?.water_health`
- Spatial Hierarchy Banner - PIXEL level (lines 427-431): MetricRow shows "Water Health" with pixelWaterHealth displayed as percentage
- CELL level Water (line 455): cellWater shown separately (cell aggregate)
- PIXEL vs CELL distinction visually presented as 3 distinct spatial hierarchy cards

**Test Requirements**:
- TR-7.1 (rule): ✅ `pixel.water_health` extracted; no null-access exceptions (guarded with ?. and nodata check)
- TR-7.2 (rubric): ✅ Pixel row + Cell row side-by-side in 3-level banner. Score: 2/2 ≥ 1 threshold.

**Completion Evidence**:
- DeepAnalysisOverlay.jsx line 126, 427-431, 455

---

## Task 8: VERIFY Existing NDVI Pixel Click Raster Integrity (Regression)

**Priority**: high
**Status**: completed (static audit done; runtime TBD in Task 9)
**Maps AC**: AC-2.1, AC-2.2, AC-3.1

**Depends**: None (regression audit)

**Files**:
- READ-ONLY: [routes.py get_ndvi_pixel_value](file:///c:/Users/DRASHITH%20HEGDE/OneDrive/Desktop/GeoSense/server/app/api/routes.py#L357-L410)
- READ-ONLY: [routes.py get_point_analysis](file:///c:/Users/DRASHITH%20HEGDE/OneDrive/Desktop/GeoSense/server/app/api/routes.py#L498-L727)

**Work**: ✅ Static audit completed
1. `get_ndvi_pixel_value()` uses `Window(col, row, 1, 1)` read (line 396) - never loads whole GeoTIFF ✅
2. Uses `dataset.index(lon, lat)` → exact raster pixel match ✅
3. Checks `dataset.nodata` and `np.isfinite` → nodata semantics ✅
4. Rounds to 3 decimals → value returned directly, no cell DB lookup ✅
5. `analysis/point` keeps `pixel.ndvi` from pixel endpoint (line 515-529) separately from `cell.metrics.ndvi` (SQL spatial_cells join at line 685) → PIXEL ≠ CELL ✅

**Test Requirements**:
- TR-8.1 (rule): ✅ Static audit: Window 1×1 read confirmed at routes.py line 396.
- TR-8.2 (rule): ✅ Static audit: pixel.ndvi uses endpoint; cell.metrics.ndvi uses SQL. Distinct sources confirmed.

**Completion Evidence**:
- routes.py line 395-396: `row, col = dataset.index(...)` + `Window(col,row,1,1)`
- routes.py line 515-602: pixel block uses pixel endpoints; line 608-692: cell block uses spatial_cells SQL

---

## Task 9: Validation — Runtime Evidence Gathering + Final Report

**Priority**: high (final acceptance gate)
**Status**: pending
**Maps AC**: All

**Depends**: T3, T5 implemented, T1-T2/T4/T6-T7/T8 complete

**Work**:
Run application (backend + frontend). Report:
1. Why the old NDVI heatmap was visible (root cause analysis)
2. Which old layer/source was responsible
3. Which raster layer is now primary NDVI surface
4. NDVI scientific raster resolution
5. Water Health raster resolution
6. Water Health raster generation method
7. Pixel query implementation for both metrics
8. Mapbox sources/layers used
9. Old layers removed/disabled
10. Runtime tests performed
11. Exact test results (pass/fail/blocked with reason)
12. Remaining limitations (e.g., GEE unavailable during impl)

Mapbox runtime checks:
- `map.getStyle().sources` for ndvi-surface, water-health-surface
- `map.getStyle().layers` for ndvi-surface-raster, water-health-surface-raster
- Layer visibility, order, opacity
- Network request for raster PNG asset
- Browser console errors

Pixel endpoint checks:
- NDVI: GET `/api/surfaces/ndvi/value?lon=72.87&lat=19.07`
- Water Health: valid pixel vs non-water pixel
- Deep Analysis: pixel + cell + muni all 3 levels present and distinct

**Test Requirements**:
- TR-9.1 (rule): Full Mapbox source/layer audit table for both metrics
- TR-9.2 (rule): Static OR runtime evidence with explicit limitation statement if env blocked

**Completion Evidence**: TBD
