# GeoSense

Environmental intelligence for Indian cities from real satellite and ground-station data:
vegetation (NDVI), land surface temperature (LST), Water Health, air quality (CPCB AQI) and a
composite stress index, analysed on a 300 m grid with machine learning and explained with cited
retrieval-augmented generation (RAG).

| City | Study region | 300 m cells |
|---|---|---|
| **Mumbai** | Mumbai, Thane and Mira-Bhayandar municipal corporations | 8,287 |
| **Delhi** | National Capital Territory of Delhi | 17,004 |
| **Bengaluru** | BBMP area (243 wards, 2022 delimitation) | 8,229 |

Every value comes from real data. Missing data stays missing and is said to be missing; nothing is
filled in, borrowed from another city or made up.

---

## How it works

```text
Sentinel-2 (10 m) ──┐                         ┌─ NDVI, Water Health, NDMI GeoTIFFs ─┐
Landsat 8/9 (30 m) ─┼─ Google Earth Engine ───┼─ LST GeoTIFF                        ├─ map images (sharp/glow/halo)
OpenAQ v3 (CPCB) ───┴─ CPCB AQI → IDW ────────┴─ AQI GeoTIFF                        │
                                                                                     ├─ composite (heat + surface + air)
300 m grid (PostGIS) ─ zonal statistics per cell ─ Isolation Forests, XGBoost LST model, Water Health robust z
                                 │
FastAPI ─ click: PIXEL (exact GeoTIFF value) → 300 m CELL (live cell means + models + history) → MUNICIPALITY
        └─ explanation: evidence → rule-based findings → hybrid RAG (BM25 + bge-small, pgvector) → checked AI summary
React + Mapbox GL ─ city switcher, layers, legend, insight panel, Deep Analysis, Ask GeoSense
```

* **Layers**: NDVI (14-day Sentinel-2 median), LST (45-day Landsat median, per-city cloud QC),
  Water Health (Sentinel-2 spectral proxy on water pixels), CPCB AQI (OpenAQ CPCB-network stations,
  48 h freshness rule, IDW k=4, NoData beyond 15 km, refreshed automatically every few hours),
  composite (weights 0.40/0.35/0.25, ≥2 of 3 components, relative within each city).
* **ML per city**: Isolation Forest on land cells, per-layer Isolation Forests (value, variability,
  contrast with the surrounding 1 km), XGBoost LST-from-land-cover model with spatial block
  cross-validation (residual = "unexplained heat"), Water Health robust z, station pollutant-mix
  Isolation Forest, validation against ESA WorldCover.
* **History per city**: same-season, year-on-year change since 2023 (Mumbai and Delhi: pre- and
  post-monsoon; Bengaluru: winter and pre-monsoon), persistence, Theil-Sen trends, change Isolation
  Forest, and "which came first: heat or greenery".
* **RAG**: 59 curated, cited notes (including Delhi and Bengaluru context) plus page-level passages
  from source documents; hybrid BM25 + BAAI/bge-small-en-v1.5 retrieval fused with RRF; another
  city's local notes are never used; AI text (Gemini → Groq) is checked against the evidence and
  dropped if it adds numbers, causes or flags.

## Repository layout

```text
client/                 React + Vite + Mapbox GL frontend (deploys to Vercel / Azure Static Web Apps)
server/
  app/core/cities.py    the cities, their regions, seasons, QC thresholds; per-request city context
  app/api/              FastAPI routes (every request works on one city: ?city= or the clicked point)
  app/services/         surfaces, ML, history, RAG, provenance
  scripts/              the data pipeline (every script takes --city), setup_city.py runs it all
  migrations/           Alembic (PostGIS + pgvector)
  data/                 Mumbai data; data/cities/<city>/ for the others (boundaries in git,
                        layers and models shipped as the data bundle)
  deploy/start.sh       container start: data bundle -> database migrations -> API
deploy/DEPLOY.md        Render + Vercel, Azure secondary with automatic fallback
render.yaml             Render Blueprint (API + PostgreSQL)
docker-compose.yml      local PostGIS + pgvector (and optional dev containers)
```

## Run it locally (Windows)

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1             # install, database, Mumbai pipeline
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -PipelineOnly -City delhi
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -PipelineOnly -City bengaluru
.\run.ps1                                                         # backend + frontend, opens the browser
```

Any OS, by hand (from `server/`, Python 3.12, Postgres from `docker compose up -d db`):

```bash
pip install -r requirements-pipeline.txt
python scripts/db_init.py                          # PostGIS + pgvector + migrations
python scripts/setup_city.py --city delhi          # boundaries → cells → NDVI → Water Health → LST → NDMI
                                                   # → map images → AQI → composite → WorldCover → ML → history
uvicorn app.main:app --reload --port 8000
cd ../client && npm install && npm run dev         # http://localhost:5173
```

The satellite steps need Earth Engine credentials (`earthengine authenticate`, `GEE_PROJECT` in
`.env`) and AQI needs a free `OPENAQ_AQI_KEY`. `setup_city.py --from <step>` resumes after a failure;
each step is also a script of its own (`--city` on every one).

A fresh clone without the pipeline outputs can fetch them: `python scripts/data_bundle.py fetch --url <bundle URL>`.

## Main API

All endpoints take `?city=mumbai|delhi|bengaluru`; a request with `lon`/`lat` is answered for the city
that contains the point.

| Endpoint | |
|---|---|
| `GET /api/cities` | the cities and which layers each has |
| `GET /api/surfaces/{ndvi,lst,water-health,aqi,composite}/latest` | map layer images, legend, provenance |
| `GET /api/analysis/point?lon=&lat=` | pixel → 300 m cell → municipality |
| `GET /api/analysis/point/explain?lon=&lat=&focus=` | findings, ML, history, relationships, cited sources |
| `POST /api/assistant/ask` | grounded question answering about a place |
| `GET /api/ml/summary`, `/api/ml/hotspots` | model cards and flagged cells |
| `GET /api/provenance`, `/api/system/status`, `/api/health` | data freshness and pipeline status |

## Deploy

See [deploy/DEPLOY.md](deploy/DEPLOY.md): Render (API + PostgreSQL with PostGIS and pgvector) and
Vercel as the main deployment, Azure (App Service, Database for PostgreSQL, Blob Storage, Static Web
Apps) as a secondary one; the frontend switches to the Render API by itself when the Azure one stops.

## Tests

```bash
cd server && python -m pytest tests -q      # database tests run when Postgres is reachable
```

## Data sources and licences

Sentinel-2 (ESA Copernicus), Landsat 8/9 (USGS) via Google Earth Engine; OpenAQ v3 (CPCB-network
stations); ESA WorldCover 2021; boundaries: OpenStreetMap (Mumbai), DataMeet Municipal Spatial Data
(Delhi, Bengaluru; CC BY-SA 2.5 India). Knowledge-base citations are listed with every note.
