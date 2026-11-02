# Environmental Surface Architecture Specification: NDVI & Water Health

## Problem

The environmental visualization architecture currently uses inconsistent spatial models for NDVI and Water Health. The scientific raster data (Sentinel-2, ~10m) exists and is used as a backend source of truth, but the frontend Mapbox rendering may fall back to polygon/cell-based choropleth paths. Water Health has NO pixel-level raster surface at all — it is rendered only as water-body polygon fills. This breaks the intended architecture:

```
SCIENTIFIC RASTER PIXEL → Mapbox Continuous Raster Surface → Clicked Pixel Value
```

Instead of:

```
CELL AGGREGATE → Polygon Choropleth / Heatmap
```

Spatial cells (8,287 cells at ~300m) are an analytical aggregation layer only — they must not be the environmental visualization grid. PIXEL ≠ CELL ≠ MUNICIPALITY.

## Users & Goals

- **Primary user**: GeoSense GIS operator viewing environmental surfaces in the Mapbox interface
- **Secondary user**: Analyst clicking locations for pixel-level scientific values and 3-level Deep Analysis context
- **Goal**: NDVI and Water Health both render as continuous satellite-derived raster surfaces (not polygons)
- **Goal**: Click queries return exact scientific raster pixel values (not cell averages)
- **Goal**: Deep Analysis returns pixel + cell + municipality as three distinct hierarchical levels

## Non-Goals

- Do NOT redesign: database architecture, spatial_cells table, RAG, XGBoost, AQI methodology, LST methodology, existing scientific NDVI formulas, existing Water Health formulas, overall GeoSense UI
- Do NOT recreate zones or modify zone/zone_json for environmental visualization
- Do NOT use Mapbox `heatmap` layer type for these metrics
- Do NOT change the Sentinel-2 NDVI GeoTIFF methodology or Cloud-Mask QA60 approach

---

## Functional Requirements

### FR-1 NDVI PRIMARY VISUAL ARCHITECTURE (Raster, not cells/zones)

NDVI shall render as a continuous Mapbox raster layer sourced from the Sentinel-2 NDVI scientific GeoTIFF via a colorized RGBA PNG overlay.

Architecture chain:
1. `server/data/surfaces/ndvi/ndvi_*.tif` (scientific source of truth, float32, ~10 m, -1..1, NoData=-9999)
2. `server/data/surfaces/ndvi/ndvi_*.png` (RGBA visualization only)
3. `GET /api/surfaces/ndvi/latest` → returns `image_url` + `coordinates`
4. Mapbox `image` source → Mapbox `raster` layer

The PNG is visualization only. Pixel queries read the GeoTIFF, never the PNG.

- The frontend shall NOT use the 8,287 spatial cells as visible NDVI polygons. Municipality boundaries may remain as context/selection outlines.

### FR-2 REMOVE / DISABLE OLD NDVI VISUALIZATION PATHS

All old polygon-based NDVI visualization paths must be disabled or hidden when the NDVI metric is active:
- Old zone/cell choropleth using fill-color driven by `ndvi_norm` data expressions on municipality or cell polygon layers
- Any visible 300 m cell boundaries
- heatmap layers
- fill-extrusion polygon mosaics

The only environmental surface when NDVI is selected must be solely the `ndvi-surface-raster` raster layer (plus municipality outlines for context only, not for data display).

### FR-3 NDVI VISUAL STYLE: CONTINUOUS RASTER

Appearance matches existing GeoSense futuristic GIS aesthetic:
- Dark near-black basemap context preserved
- Low/subdued NDVI (near-zero NDVI  transparent/subdued via the alpha ramp already in ndvi_surface._ndvi_rgba)
- Stronger vegetation progressively brighter green
- Smooth spatial transitions (linear raster resampling)
- No visible grid, cell, cell boundaries, polygon mosaic, artificial rectangular glow around raster footprint
- Does not claim or imply visual smoothing increases scientific resolution (~10 m stays ~10 m)

### FR-4 NDVI PIXEL CLICK ENDPOINT

`GET /api/surfaces/ndvi/value?lon=&lat= must stay the current architecture:
1. Map clicked lon/lat → Rasterio `dataset.index(lon, lat) → 1×1 `Window(col, row, 1, 1)` → exact corresponding Sentinel-2 NDVI GeoTIFF pixel → return value.
- It must NOT → cell lookup → cell average
- It must NOT load the entire GeoTIFF
- It must NOT read values from the colorized PNG

### FR-5 NDVI THREE-LEVEL ANALYSIS

`GET /api/analysis/point?lon=&lat=` returns location / pixel / cell / municipality.

NDVI-specific:
- `pixel.ndvi.value` = exact scientific Sentinel-2 raster pixel
- `cell.metrics.ndvi` = 300m analytical cell aggregate (different from pixel!)
- `municipality` = admin context only
- Never substitute cell.metrics.ndvi for pixel.ndvi.

### FR-6 WATER HEALTH NEW PRIMARY RASTER SURFACE

Water Health must follow the same raster spatial model as NDVI.

Scientific chain:
1. Sentinel-2 source bands (B3 Green, B4 Red, B5 Red-Edge, B8 NIR, B11 SWIR)
   MNDWI = (B3-B11)/(B3+B11)
   NDCI proxy = (B5-B4)/(B5+B4)
   Turbidity proxy = (B3-B4)/(B3+B4)
   Water mask via MNDWI ≥ 0.0
2. Water Health score = project-established methodology
3. Scientific Water Health GeoTIFF (0..1 float32, NoData=-9999, NULL/transparent for non-water)
4. Colorized RGBA PNG Water Health score  → Mapbox image source → Mapbox raster layer
5. Water pixels = NoData/NULL/transparent and must NOT become Water Health = 0.

Existing formulas:
- Reuse:
- from ingest_ndvi_ndwi.py calculate_water_health_score() algorithm exactly.
- New:
- pixel-level instead of only cell-level aggregates.

### FR-7 WATER HEALTH VISUALIZATION

Water Health renders as a continuous raster surface.

No:
- zone polygons
- spatial cell polygons
- visible analytical grid
- point heatmaps
- marker cloud
- LST color ramp reuse

Dedicated Water Health color ramp reflecting the metric semantics:
- Non-water → transparent/NULL
- Healthy water → cyan/teal → green → yellow → orange → red for → watch → concern

GeoSense futuristic sensor aesthetic compatible.

### FR-8 WATER HEALTH PIXEL CLICK ENDPOINT

New endpoint (or match project conventions):
`GET /api/surfaces/water-health/value?lon=&lat=`

Requirements:
1. Map lon/lat → corresponding scientific Water Health GeoTIFF raster pixel
2. Localized 1×1 windowed raster read
3. Return actual Water Health value (0..1 float)
4. Return NULL/NoData/Unavailable for non-water pixels
5. Never read colorized PNG
6. Never substitute cell-level water_health_score average

Conceptual response (follow project naming):
```json
{
  "metric": "water_health",
  "longitude": 72.87,
  "latitude": 19.07,
  "value": 0.72,
  "nodata": false,
  "source": "Sentinel-2 derived Water Health raster",
  "resolution_m": 10
}
```

### FR-9 MAP LAYER ARCHITECTURE AUDIT & CORRECTION

Mapbox runtime audit requirements for each metric:

| Check | NDVI | Water Health |
|---|---|---|
| Source exists | image source? | image source? |
| Raster layer exists | raster layer? | raster layer? |
| Correct coordinates/bounds | ✓ | ✓ |
| Visibility correct on metric toggle | visible only when NDVI active | visible only when WH active |
| Opacity correct | raster-opacity tuned | raster-opacity tuned |
| Layer ordering correct | raster below muni outlines | raster below muni outlines |
| No old polygon/cell layers as env surface | no old choropleth visible | no water-body polygon fill visible (raster supersedes) |

Active environmental layer when a metric is selected = its raster surface. Municipality boundary/extrusion may remain above/below for context/selection ONLY (0 opacity or near-zero for environmental data display).

### FR-10 DEEP ANALYSIS: WATER HEALTH PIXEL LEVEL

`GET /api/analysis/point` shall include `pixel.water_health` block alongside the existing pixel.ndvi, pixel.lst, pixel.aqi.

Hierarchy intact:
- pixel.water_health = exact raster pixel (NULL/NoData for non-water)
- cell.metrics.water_health_score = 300m cell aggregate
- municipality = admin

### FR-11 WATER HEALTH SURFACE FETCH IN FRONTEND

useGeoSenseData shall fetch `/api/surfaces/water-health/latest` (parallel to ndviSurface) and pass waterHealthSurface through to useMapbox, which shall set up the image source + raster layer analogous to NDVI.

Old WATER_FILL polygon fill-color choropleth shall be hidden when water health raster surface is available (surface mode). WATER_OUTLINE may remain or be hidden (TBD during implementation, prefer outline for compatibility if it does not duplicate).

---

## Non-Functional Requirements

### NFR-1 NO SCIENTIFIC INTEGRITY

Visual smoothing / interpolation displayed value queries = source Sentinel-2 NDVI GeoTIFF
- Water Health visual pixel values = source Water Health GeoTIFF derived via project formulas
- Never: "looks smoother" does not mean "resolution increased past 10 m"

### NFR-2 CONSISTENCY

Consistency with existing backend service pattern

NDVI surface service patterns (ndvi_surface.py) → reuse architectural consistency:
- manifest.json entry per surfaces/water-health/ directory with both GeoTIFF + PNG
- manifest.json updated with water_health record
- API endpoints consistent naming conventions consistent with the existing /api/surfaces/... pattern

### NFR-3 PERFORMANCE

Pixel queries: localized  window 1×1), not whole-GeoTIFF loads.
Raster assets loaded once per surface change.

### NFR-4 EXISTING BACKWARD COMPATIBILITY

Existing endpoint contracts unchanged:
- `GET /api/surfaces/ndvi/value → unchanged response
- GET /api/analysis/point → adds pixel.water_health only; existing fields preserved

---

## Constraints

1. Reuse existing scientific formulas from ingest_ndvi_ndwi.py.
2. Do not redesign spatial_cells, zones, DB schema migrations except for the new surface files and API route additions.
3. Mapbox raster layer type only (no heatmap).
4. Non-water Water Health pixels = NoData/NULL transparent, not 0.
5. GeoSense futuristic GIS aesthetic preserved (no generic heatmap look).

## Dependencies (Existing:
- Sentinel-2 via Google Earth Engine (GEE)
- rasterio + Pillow + NumPy (already used by ndvi_surface.py pattern already established)
- mapbox-gl (existing)
- FastAPI routes.py (extend existing endpoints

## Assumptions

1. The existing NDVI scientific GeoTIFF at ~10 m resolution is the source of truth and correct.
2. GEE EE + is reachable.
3. Mumbai study extent bounds are the same as used for the NDVI export.
4. Water Health pixel-level calculation is computationally tractable over the same extent (same as / analogous to NDVI.

## Open Questions

None. The requirements.

---

## Acceptance Criteria

### Rule AC-1: NDVI Raster is the visible when NDVI is selectedAC-1.1 rule Mapbox runtime: source `ndvi-surface` source `type = image and layer `ndvi-surface-raster` type=raster exists and has visibility=visible.
AC-1.2 rule No old cell/zone/choropleth polygon fill-extrusion data-colored with `ndvi_norm` expression is simultaneously visible with opacity>0.20 when NDVI is active.
AC-1.3 rule No visible 300m cell boundaries or rectangular glow footprint glow artifacts.

### Rule AC-2: NDVI Pixel Click Returns Scientific GeoTIFF Pixel
AC-2.1 rule Clicked lon/lat sent to /api/surfaces/ndvi/value returns exact Sentinel-2 NDVI rounded to 3 decimals.
AC-2.2 rule The endpoint response does not and does not return a cell average.

### Rule AC-3: NDVI 3-Level Distinct
AC-3.1 rule `GET /api/analysis/point returns pixel.ndvi.value ≠ cell.metrics.ndvi (unless numerically equal by coincidence the three fields are distinct sources).

### Rule AC-4: Water Health Raster Exists
AC-4.1 rule A scientific Water Health GeoTIFF + PNG exist under server/data/surfaces/water-health/ and manifest.json has a water_health record with generation_status=generated.
AC-4.2 rule Water Health non-water pixels are NoData=-9999 and transparent in the PNG, not zero.

### Rule AC-5: Water Health Raster is the Primary Visual
AC-5.1 rule Water Health selected → water_ raster layer visible.
AC-5.2 rule WATER_FILL polygon water_health polygon choropleth NOT simultaneously visible with opacity>0.20 when raster is available (surface mode)
AC-5.3 rule No spatial cells visible.

### Rule AC-6: Water Health Pixel Click Endpoint
AC-6.1 rule GET /api/surfaces/water-health/value returns value and resolution_m, nodata fields.
AC-6.2 rule Non-water click → nodata=true and value=null
AC-6.3 rule Valid water pixel click → nodata=false value ∈ [0, 1] rounded to 2-3 decimals

### Rule AC-7: Deep Analysis 3-Level Water Health
AC-7.1 rule GET /api/analysis/point contains pixel.water_health { value, nodata, source, resolution_m }.

### Rubric AC-8: Visual Quality
AC-8.1 rubric Visual GeoSense aesthetic quality of the environmental surfaces (NDVI green ramp looks like a satellite vegetation sensor readout:
- 0–1 scale: 0 = invisible / subdued urban transparent → low 0.05 → transparent 0.35+, green intensity ramp, no generic heatmap "blob" look
Water Health cyan→green→yellow→orange→red ramp matches water semantics.
Scale: 0 (unusable), 1 (healthy→ concern → healthy.
Score: 0–2; pass threshold ≥ 1.5

### Rubric AC-9: Layer Order & Opacity
AC-9.1 rubric Layer ordering and opacities: Municipality context outlines only on top of raster for selection context; raster clearly above basemap; between.
No conflict between layers visually.
Score: 0–2; pass ≥ 1.5
