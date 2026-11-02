# GeoSense

GeoSense is a Mumbai environmental intelligence platform built around a PostGIS-backed spatial data model and a FastAPI backend. The current repository reflects a backend-first implementation focused on real environmental data ingestion, temporal feature analysis, anomaly detection, and evidence-grounded explanation.

## What is implemented today

The codebase already contains the following working pieces:

- 189 Mumbai zones stored in PostGIS as MULTIPOLYGON geometries with SRID 4326
- Zone, EnvironmentData, EngineeredFeature, and AnomalyResult models in server/app/models.py
- PostgreSQL uniqueness rules for environmental observations keyed by (zone_id, observed_at)
- AQICN ingestion with provenance metadata for observed vs. estimated AQI values
- Sentinel-2 NDVI and NDWI ingestion through Google Earth Engine
- Landsat LST ingestion through Google Earth Engine
- Temporal comparisons built from prior compatible observations only
- Isolation Forest anomaly detection over complete same-day metric snapshots
- Deterministic explanations built from a validated evidence object
- Retrieval-based knowledge support for explanation enrichment
- Operational monitoring around ingestion readiness and data coverage

This project is intentionally not a frontend redesign. The frontend remains the current GeoSense UI while the backend continues to accumulate and interpret real environmental data.

---

## Architecture

```text
Data sources
  ├── AQICN
  ├── Sentinel-2
  └── Landsat

        │
        v
   PostgreSQL + PostGIS
        │
        ├── zones
        ├── environment_data
        ├── engineered_features
        └── anomaly_results

        │
        v
   FastAPI backend
        │
        ├── metrics endpoints
        ├── AQI station endpoints
        ├── anomaly endpoints
        └── explanation services
```

---

## Data layer

The real data model is centered on environment_data and its provenance. Each observation can include:

- AQI, PM2.5, PM10, NO2 and related pollutants
- NDVI and NDWI values
- LST
- source metadata and processing context
- AQI source type such as observed or estimated
- nearest-station distance for AQI interpolation

The ingestion pipeline uses idempotent upserts and preserves source metadata so later analysis remains traceable.

---

## AQI pipeline

The AQICN workflow stores direct measurements and uses interpolation-derived values where a zone does not have a direct station observation. This is tracked explicitly in provenance and is not silently treated as a direct measurement.

Key characteristics:

- direct station data is preserved
- interpolated values remain clearly identified
- missing data is left missing instead of being fabricated
- temporal and spatial provenance remain attached to the row

---

## Satellite pipelines

### NDVI / NDWI

The repository contains functioning Sentinel-2 ingestion logic for Mumbai zones and fixed-window temporal composites. The backend expects real remote-sensing values to be stored with their acquisition and configuration metadata.

### LST

Landsat-based LST ingestion is implemented separately from the NDVI/NDWI flow. It uses a fixed composite window and writes values per zone with the same provenance-aware data model.

---

## Temporal and anomaly logic

The backend includes a temporal feature pipeline that uses only prior compatible observations when calculating:

- delta
- rate of change
- baseline history
- z-score-based deviation
- trend direction
- persistence over time

The spatial anomaly pipeline uses an Isolation Forest on complete same-day feature rows. The system stores anomaly score, classification, and supporting evidence without claiming causation from the model output alone.

---

## Explanation layer

The backend contains an evidence-driven explanation stack:

- server/app/services/explanation_evidence.py builds validated evidence
- server/app/services/explanation_engine.py creates deterministic explanations
- server/app/services/rag_knowledge.py loads local knowledge for retrieval
- server/app/services/explanation_service.py coordinates retrieval and explanation flow

This design keeps explanations grounded in stored data and avoids unsupported causal claims.

---

## API surface

The modern server exposes the following backend endpoints:

- GET /api/metrics/latest
- GET /api/metrics/{locality_id}
- GET /api/aqi/stations
- GET /api/anomalies
- POST /api/anomalies/detect

These routes operate against the current Zone / EnvironmentData schema rather than the legacy locality tables.

---

## Validation and status

The codebase includes systematic validation around:

- source metadata compatibility
- temporal leakage safeguards
- missing-data guards
- anomaly persistence logic
- explanation generation
- retrieval behavior
- API compatibility checks

The project is actively in a research-validation stage: the pipeline is implemented and data is being accumulated with scientific safeguards, rather than relying on synthetic values or unsupported labels.

---

## Local development

### Frontend

```bash
npm install
npm run dev
```

### Backend

```bash
cd server
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Environment configuration should include the required database and optional external service settings for Earth Engine or LLM-based explanation features.

---

## Repository layout

```text
GeoSense/
├── client/              # React frontend
├── server/              # FastAPI backend and ingestion scripts
│   ├── app/
│   │   ├── api/
│   │   ├── services/
│   │   ├── models.py
│   │   └── database.py
│   ├── aqicn/
│   ├── gee/
│   ├── migrations/
│   ├── tests/
│   └── requirements.txt
├── README.md
├── package.json
├── vite.config.js
├── tailwind.config.js
└── .env.example
```

---

## Important note

This README reflects the repository as it currently exists: a working environmental intelligence backend built around real spatial and temporal data, formalized provenance, and explainable anomaly logic. It intentionally follows the implemented architecture rather than an older conceptual outline.
---

## Intelligence layer (Nov 2026): heatmaps · AQI · ML · RAG

**Where AI is used (and where it is not).** Every fact, model result, associated factor and recommendation in
Deep Analysis is generated from the data, the models and the cited knowledge base by rules — no LLM. The LLM
(Gemini → Groq fallback) is limited to (1) a 2–3 sentence "In plain words" summary that may only restate those
checked facts, and (2) answers in the Ask GeoSense box. Both are validated (no new numbers, no causal claims, no
model "flag" the models did not raise) and silently dropped if they fail. `AI_MODE=off` in `.env` disables AI
calls entirely.

Everything below runs on the real rasters already in `server/data/surfaces/` and the
real OpenAQ API. No value is fabricated: missing data stays NoData and is reported.

### Run order (from `server/`)

```bash
pip install -r requirements.txt
alembic upgrade head
python scripts/generate_spatial_cells.py              # 8,287 × 300 m cells (once)

python scripts/render_heatmaps.py                     # smooth, clipped NDVI / Water Health / LST PNGs
python scripts/generate_aqi_station_surface.py --cells   # OpenAQ → CPCB AQI → IDW (needs OPENAQ_AQI_KEY)
python scripts/generate_composite_surface.py          # LST + NDVI (+ AQI if available), no imputation
python scripts/run_ml_pipeline.py                     # cell features → Isolation Forest + XGBoost + WH z

uvicorn app.main:app --reload --port 8000
```

### What each piece does

| Piece | File | Notes |
|---|---|---|
| Heatmap renderer | `app/services/surfaces/heatmap_render.py`, `scripts/render_heatmaps.py` | Normalised Gaussian smoothing on raw values (NoData never leaks), glow/halo, **boundary mask applied after blur**. Water Health uses in-region p2–p98 colour stops; legend carries raw values. GeoTIFFs are never modified. |
| LST QC | `app/services/qc.py` | LST < 20 °C over Mumbai = residual cloud → hidden in maps, excluded from cell stats, flagged on click. |
| CPCB AQI surface | `app/services/surfaces/aqi_station_surface.py` | ≥3 fresh (≤48 h) CPCB/MPCB stations, IDW k=4 p=2, NoData > 15 km from stations. Otherwise `insufficient_coverage` with a station audit. The old Sentinel-5P NO₂ “AQI proxy” is retired. |
| Composite | `scripts/generate_composite_surface.py` | Heat + vegetation deficit (+ AQI only if real). Valid only where all inputs exist; open water excluded. |
| Cell features | `app/services/ml/cell_features.py` | Zonal stats per 300 m cell on each raster's native grid: NDVI mean/std, vegetation/built/open-water shares, distance to water, Water Health, LST mean/std, AQI. |
| Isolation Forest | `app/services/ml/cell_models.py` | Land cells only (< 50 % open water), land-normalised shares, 300 trees, 5 % contamination, per-feature z-scores. Water cells are scored by the Water Health robust z. |
| Per-layer Isolation Forest | `app/services/ml/cell_models.py` | One model each for NDVI, LST, Water Health and AQI: cell value, within-cell variability and contrast with the surrounding 1 km → unusually high / low / patchy. Map chips: NDVI / LST / Water Health / AQI outliers. |
| Station Isolation Forest | `app/services/ml/cell_models.py` | Real OpenAQ CPCB/MPCB stations compared on pollutant sub-indices (no imputation) → stations with an unusual pollutant mix. |
| XGBoost LST model | `app/services/ml/cell_models.py` | Predicts LST from land cover; 5-fold **spatial block CV** (~3 km). Snapshot 2026-10-07: R² 0.49, RMSE 2.9 °C. Out-of-fold residual > 2×RMSE = “unexplained heat”; TreeSHAP contributions per cell. |
| Water Health z | `app/services/ml/cell_models.py` | Median/MAD robust z among water cells; z < −2 flagged. |
| RAG | `app/services/rag/` | 42 curated, cited knowledge entries (CPCB, USGS, ESA, peer-reviewed methods, Mumbai context); BM25 retrieval; deterministic evidence write-up; optional LLM with automatic fallback (Anthropic → Gemini → Groq → OpenAI) whose output is rejected if it adds numbers, unknown citations or causal claims. |

### New endpoints

- `GET /api/analysis/point/explain?lon=&lat=` — evidence + signals + ML + recommendations + citations
- `POST /api/assistant/ask` — `{question, lon?, lat?}` grounded Q&A
- `GET /api/ml/summary` · `GET /api/ml/hotspots?model=isolation_forest|heat_residual|water_health`
- `GET /api/knowledge?q=` · `POST /api/ml/run`
- `GET /api/surfaces/aqi/latest` now always returns `available` + `reason` + station audit

### Frontend

- Deep Analysis (each tab is focused on its layer: signals, AI write-up, suggested questions) → “Environmental Intelligence Evidence” shows the AI write-up, XGBoost contribution bars, Isolation Forest deviations, recommendations, RAG sources and an **Ask GeoSense** box; the right column shows live city model cards.
- Layer panel → **ML Hotspots** overlay (outliers / unexplained heat / low water condition) and an honest AQI-unavailable message.

Tests: `python -m pytest tests/test_intelligence_layer.py` (14 tests).
