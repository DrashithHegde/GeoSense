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