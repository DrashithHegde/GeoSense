# 🌍 GeoSense

**GeoSense** is a research-oriented urban environmental intelligence platform that monitors environmental conditions across city zones using real-time air-quality data and satellite-derived indicators.

It combines:

- 🌫️ **AQI** — air pollution intensity
- 🌿 **NDVI** — vegetation health
- 💧 **NDWI** — surface water / moisture conditions
- 🌡️ **LST** — Land Surface Temperature
- 🤖 **Isolation Forest** — spatial environmental anomaly detection
- 📈 **Temporal analysis** — historical changes, deltas, baselines and trends
- 🧠 **RAG + LLM explanations** — grounded natural-language interpretation of detected anomalies

GeoSense is currently developed and validated for **Mumbai**, with the architecture intentionally designed to support additional cities such as **Bengaluru and New Delhi** without rebuilding the core system.

---

# 🎯 Motivation

Urban environmental problems rarely occur in isolation.

Vegetation stress, surface-water changes, elevated temperatures and air pollution can interact spatially across a city. Traditional monitoring systems often expose these indicators separately, making it difficult to identify unusual combinations of environmental conditions.

GeoSense addresses this by creating a common spatial framework in which multiple environmental indicators can be analyzed together.

The goal is **not to claim physical causation**, but to identify statistically unusual environmental patterns and provide evidence-grounded explanations for why a zone was flagged.

---

# 🧠 How GeoSense Works

```text
                  ┌─────────────────────┐
                  │      Data Sources   │
                  └──────────┬──────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
          AQICN/API      Sentinel-2      Landsat
              │              │              │
              │          NDVI / NDWI        LST
              │              │              │
              └──────────────┼──────────────┘
                             ▼
                    ┌─────────────────┐
                    │  Spatial Zones  │
                    │   (PostGIS)     │
                    └────────┬────────┘
                             ▼
                    ┌─────────────────┐
                    │ Feature Pipeline│
                    └────────┬────────┘
                             │
                 ┌───────────┴───────────┐
                 ▼                       ▼
          Temporal Features       Spatial Features
                 │                       │
                 └───────────┬───────────┘
                             ▼
                    ┌─────────────────┐
                    │ Isolation Forest│
                    └────────┬────────┘
                             ▼
                    ┌─────────────────┐
                    │ Anomaly +       │
                    │ Evidence        │
                    └────────┬────────┘
                             ▼
                  ┌──────────────────────┐
                  │ Explanation Layer    │
                  │ Deterministic + RAG  │
                  │ + Optional LLM       │
                  └──────────┬───────────┘
                             ▼
                       FastAPI / Frontend
📊 Environmental Indicators
🌫️ AQI

National Air Quality Index data is collected from AQICN sources.

Where direct station coverage is unavailable, GeoSense derives zone-level AQI using IDW (Inverse Distance Weighting) while preserving provenance describing whether the value was directly observed or estimated.

The system does not fabricate values for zones where interpolation is not scientifically justified.

🌿 NDVI

Normalized Difference Vegetation Index

Used as an indicator of vegetation condition.

GeoSense derives NDVI from Sentinel-2 imagery using fixed temporal composite windows.

💧 NDWI

Normalized Difference Water Index

Used to identify spatial variation in surface water and moisture-related conditions.

NDWI is derived alongside NDVI from Sentinel-2 imagery.

🌡️ LST

Land Surface Temperature

Derived from Landsat 8/9 Level-2 thermal products.

LST is used to identify spatial heat patterns and potential urban heat concentrations.

Because satellite thermal imagery can be unavailable during periods of heavy cloud cover, GeoSense explicitly preserves NULL values rather than fabricating or imputing observations.

🤖 Spatial Anomaly Detection

GeoSense currently uses Isolation Forest for unsupervised spatial anomaly detection.

Rather than relying on manually chosen environmental thresholds, the model evaluates the combination of environmental features across city zones and identifies statistically unusual spatial patterns.

For example, a zone may be unusual because of:

unusually high temperature relative to other zones
unusually low vegetation index
unusual water-index behavior
unusual AQI
an uncommon combination of multiple indicators

The system stores the resulting anomaly classification and supporting evidence in PostgreSQL/PostGIS.

Important distinction

GeoSense does not interpret an anomaly as proof of physical causation.

Instead:

Isolation Forest identifies unusual patterns, while statistical feature deviations provide evidence about which variables contributed most strongly to the detected anomaly.

📈 Temporal Analysis

GeoSense is designed to move beyond single snapshots.

Temporal features include:

Delta
Rate of change
Historical baselines
Z-score deviations
Trend information
Anomaly persistence

Temporal calculations use strictly prior observations to prevent future information from leaking into the current analysis.

Temporal features are only produced when sufficient compatible historical observations exist.

No synthetic historical observations are created to satisfy model requirements.

For scientifically meaningful long-term trends, GeoSense is designed to accumulate approximately 6–12 months of real observations covering Mumbai's seasonal cycle.

🔐 Data Provenance & Scientific Safeguards

A major design principle of GeoSense is that environmental intelligence must remain traceable to its source data.

Relevant observations store provenance describing information such as:

source dataset
observation/composite window
processing configuration
spatial interpolation method
cloud/masking configuration
processing scale
AQI observation vs. estimation status

Temporal compatibility checks ensure that historical observations produced under incompatible processing configurations are not silently compared.

The system also maintains database-level uniqueness and idempotent ingestion so that rerunning an ingestion does not create duplicate observations.

🧠 Explanation & RAG Layer

GeoSense contains two explanation layers.

1. Deterministic Explanation

The backend first constructs a validated evidence object from the database.

This includes:

environmental measurements
anomaly classification
anomaly score
statistical deviations
temporal availability
provenance
data-quality information

The deterministic explanation is generated directly from this evidence.

2. RAG + LLM Explanation

An optional LLM layer can enrich the deterministic explanation using a small domain knowledge corpus covering topics such as:

Indian AQI interpretation
NDVI
NDWI
LST
urban environmental stress
Mumbai environmental context
Isolation Forest interpretation

The LLM never receives unrestricted database access.

Instead:

PostgreSQL
     │
     ▼
Validated Evidence
     │
     ├──────────────► Deterministic Explanation
     │
     ▼
Knowledge Retrieval
     │
     ▼
LLM
     │
     ▼
Validated Explanation

If the LLM is unavailable or produces invalid/unsupported content, GeoSense falls back to the deterministic explanation.

The explanation layer is explicitly designed to avoid unsupported causal claims such as:

"X caused Y."

Instead, the system uses language such as:

"X was identified as a strong statistical contributor to the anomaly."

🗺️ Geographic Architecture

GeoSense currently operates on 189 spatial zones covering Mumbai.

The geographic architecture is intentionally city-agnostic.

The long-term goal is to support:

GeoSense
├── Mumbai
├── Bengaluru
└── New Delhi

without duplicating the underlying ingestion, feature-engineering, anomaly-detection and explanation architecture.

City-specific environmental context can be supplied independently through the knowledge layer.

🛠️ Technology Stack
Frontend
Technology	Role
React 18	Component-based UI
Vite	Development/build tooling
Tailwind CSS	UI styling
Mapbox GL JS	Interactive geographic visualization
Framer Motion	UI animations
React Icons	Interface icons
Backend
Technology	Role
FastAPI	REST API
Python	Backend & data processing
PostgreSQL	Primary database
PostGIS	Spatial database functionality
SQLAlchemy	Database interaction
GeoPandas	Spatial processing
scikit-learn	Isolation Forest
Google Earth Engine	Satellite data processing
AQICN	Air-quality source
Pydantic	Data validation
Uvicorn	ASGI server
AI / Explanation
Component	Role
Isolation Forest	Unsupervised spatial anomaly detection
Rule-based retrieval	Lightweight RAG retrieval
Gemini	Optional LLM explanation layer
JSONL knowledge base	Environmental domain knowledge

No vector database is currently required because the initial knowledge corpus is intentionally small and deterministic retrieval is sufficient.

🔌 Backend API

Current backend endpoints include:

GET /api/health
GET /api/system/status
GET /api/anomalies
GET /api/metrics/latest
GET /api/aqi/stations
GET /api/zones/{zone_id}/explanation
/api/system/status

Provides read-only operational monitoring including:

raw-data integrity
observation counts
provenance coverage
AQI coverage
temporal readiness
anomaly readiness
scheduler configuration
XGBoost readiness
🗄️ Data Architecture

The primary environmental data is stored in PostgreSQL/PostGIS.

Conceptually:

zones
  │
  ▼
environment_data
  │
  ├── AQI
  ├── NDVI
  ├── NDWI
  └── LST
  │
  ▼
engineered_features
  │
  ▼
anomaly_results

The database maintains uniqueness on:

(zone_id, observed_at)

and ingestion uses idempotent upserts.

⏱️ Scheduler & Ingestion

GeoSense contains an operational scheduler designed to collect data according to the native cadence of each source.

The ingestion architecture supports:

AQI ingestion
Sentinel-2 ingestion
Landsat ingestion
provenance preservation
retry handling
idempotent upserts
same-day feature gating

A feature/anomaly snapshot is only executed when the required environmental inputs are legitimately available.

For example, if Landsat LST is unavailable for a particular date because of cloud/imagery limitations, GeoSense does not force the anomaly model to run using fabricated or substituted LST values.

🧪 Validation & Testing

GeoSense places significant emphasis on reproducibility and data integrity.

The backend contains automated tests covering:

ingestion timestamp handling
provenance compatibility
temporal leakage protection
scheduler gating
feature guards
Isolation Forest persistence
API endpoints
operational monitoring
deterministic explanations
RAG retrieval
LLM validation/fallback behavior

The latest verified backend test suite contains:

75 tests — 75 passed.

Live database verification has also confirmed:

no duplicate environmental observation keys
idempotent ingestion
preserved legacy data
persisted anomaly results
provenance-bearing observations
API/database consistency
🚧 Current Status
Component	Status
Mumbai spatial zoning	✅ Implemented
AQICN ingestion	✅ Implemented
AQI spatial interpolation	✅ Implemented
Sentinel-2 NDVI	✅ Implemented
Sentinel-2 NDWI	✅ Implemented
Landsat LST ingestion	✅ Implemented
Data provenance	✅ Implemented
Idempotent ingestion	✅ Implemented
Temporal feature engine	✅ Implemented
Isolation Forest	✅ Implemented
Operational monitoring	✅ Implemented
FastAPI API	✅ Implemented
Deterministic explanations	✅ Implemented
RAG knowledge layer	✅ Implemented
Optional Gemini explanation	✅ Implemented
Long-term temporal modeling	🟡 Collecting history
Multi-city support	🔜 Future expansion
XGBoost supervised prediction	⏸️ Intentionally deferred
Composite environmental risk score	⏸️ Not implemented
IMD integration	🔜 Future
Advanced RAG/vector database	🔜 Future
⚠️ Why XGBoost Is Currently Deferred

XGBoost was considered for advanced supervised environmental modeling.

However, GeoSense currently does not have a scientifically legitimate supervised ground-truth target for predicting environmental risk.

Training a model using an arbitrary or synthetic risk label would make the resulting predictions scientifically questionable.

Therefore:

XGBoost is intentionally deferred until a legitimate supervised target and sufficient real historical data are available.

The current architecture prioritizes real observations, temporal integrity and explainability over prematurely adding another ML model.

🔬 Research Principles

GeoSense follows several core principles:

1. Real data over synthetic data

No artificial environmental history is generated to make models appear ready.

2. Provenance over convenience

Environmental observations remain traceable to their source and processing configuration.

3. No temporal leakage

Future observations cannot influence historical feature calculations.

4. Missing data stays missing

Unavailable satellite observations are represented explicitly rather than fabricated.

5. Anomaly ≠ causation

Statistical contribution is not presented as proof of physical causation.

6. Explainability must be evidence-grounded

LLMs can explain validated evidence but cannot invent measurements or override the underlying data.

7. Model complexity follows data maturity

Advanced supervised ML is introduced only when sufficient real-world data and a defensible target exist.

🌆 Future Expansion

The architecture is designed to evolve from a Mumbai-focused research prototype into a multi-city environmental intelligence platform.

Potential future cities:

Mumbai
Bengaluru
New Delhi

Future development may include:

longer-term seasonal analysis
improved thermal-data coverage
additional meteorological sources
IMD integration
supervised environmental forecasting
richer RAG knowledge bases
advanced vector retrieval
multi-city comparison
additional environmental indicators
production deployment
🚀 Quick Start
Frontend
npm install
npm run dev

The frontend development server runs at:

http://localhost:5173
Backend

Create/activate the project virtual environment and install dependencies:

python -m venv .venv

# Windows
.\.venv\Scripts\activate

pip install -r server/requirements.txt

Configure the required environment variables in:

server/.env

The .env file should never be committed.

🔑 Environment Variables

The frontend requires a Mapbox token:

VITE_MAPBOX_TOKEN=your_mapbox_token

The backend may require configuration for:

DATABASE_URL=...
GEE_PROJECT=...
AQICN_TOKEN=...
GEMINI_API_KEY=...

GEMINI_API_KEY is optional.

If it is unavailable, GeoSense continues to provide the deterministic explanation layer.

📁 High-Level Project Structure
GeoSense/
│
├── src/                         # React frontend
│
├── server/
│   ├── app/
│   │   ├── api/                 # FastAPI routes
│   │   ├── core/                # Configuration
│   │   ├── models/              # Database models
│   │   ├── schemas/             # Pydantic schemas
│   │   └── services/
│   │       ├── temporal/        # Temporal features
│   │       ├── operational/     # System monitoring
│   │       └── ...
│   │
│   ├── aqicn/                   # AQI ingestion & IDW
│   ├── gee/                     # Earth Engine pipelines
│   ├── scripts/                 # Operational/verification scripts
│   ├── tests/                   # Backend tests
│   └── requirements.txt
│
├── rag_knowledge.jsonl          # Environmental knowledge corpus
│
├── .env.example
└── README.md
📌 Project Status

GeoSense is currently in an operational research-validation stage.

The core data ingestion, spatial anomaly detection, temporal safeguards, API layer, provenance system and evidence-grounded explanation architecture are implemented.

The system is now focused on accumulating legitimate longitudinal environmental observations before introducing more complex supervised modeling.

🌍 GeoSense

Observe → Validate → Detect → Explain

A research framework for understanding unusual environmental patterns across urban regions.