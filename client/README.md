# GeoSense

GeoSense monitors urban environmental health using satellite-derived indicators such as NDVI (vegetation health), NDWI (surface water presence), Land Surface Temperature (LST), and National Air Quality Index (AQI). It detects abnormal spatial patterns across city zones to highlight emerging environmental stress and ecological risk.

---

## 🌍 GeoSense: Spatial Environmental Anomaly Detection Framework

GeoSense is a research-oriented environmental intelligence framework designed to detect spatial ecological anomalies in urban regions using multi-indicator satellite-derived features and air quality metrics.

The system integrates vegetation health (NDVI), surface water presence (NDWI), Land Surface Temperature (LST), and National Air Quality Index (AQI) to model environmental stress patterns and identify abnormal spatial behavior across city zones.

---

## 📌 Research Motivation

Urban ecosystems are increasingly impacted by:

- Vegetation degradation
- Surface water depletion
- Urban heat island intensification
- Rising atmospheric pollution

Existing monitoring systems typically evaluate these indicators independently. GeoSense proposes a multi-dimensional spatial anomaly detection approach to identify compounded environmental stress signals.

---

## 🧠 Methodological Overview

GeoSense follows a structured environmental analytics pipeline:

**Spatial Zoning**
- Urban areas are partitioned into geographic zones.
- Each zone represents a spatial unit for analysis.

**Feature Extraction**
- NDVI → Vegetation health
- NDWI → Surface water presence
- LST → Surface heat distribution
- AQI → Air pollution intensity

**Feature Normalization**
- Environmental indicators are scaled to ensure comparability.

**Anomaly Detection (Phase 1)**
- Isolation Forest is applied to detect spatial outliers.
- Zones with abnormal environmental feature combinations are flagged.

---

## 📊 Environmental Indicators

**NDVI (Normalized Difference Vegetation Index)**
Quantifies vegetation density and vitality. Lower NDVI values may indicate vegetation stress or land degradation.

**NDWI (Normalized Difference Water Index)**
Measures surface water presence and moisture variability. Useful for detecting shrinking water bodies or hydrological stress.

**LST (Land Surface Temperature)**
Derived from thermal satellite data. Used to identify heat concentration and urban heat islands.

**AQI (Air Quality Index)**
Represents aggregated air pollutant concentration levels. Higher values indicate deteriorating atmospheric conditions.

---

## 🔍 Spatial Anomaly Modeling

GeoSense does not rely on threshold-based classification.

Instead, it evaluates multi-feature environmental behavior across zones and detects statistically rare patterns. An anomaly may represent:

- Concurrent vegetation decline and heat increase
- Water body reduction with rising AQI
- Abnormal environmental combinations relative to neighboring zones

This enables early detection of emerging ecological risk clusters.

---

## 🗺️ Visualization Layer

The system presents:

- Zone-based spatial heatmaps
- Gradient environmental intensity mapping
- Clear anomaly highlighting
- Minimal, research-focused geographic interface

Visualization emphasizes interpretability over visual clutter.

---

## 🛠️ Technical Framework (Phase 1)

**Frontend (implemented)**
| Package | Version | Role |
|---|---|---|
| React | 18.3 | UI component framework |
| Vite | 5.4 | Build tool & dev server |
| Tailwind CSS | 3.4 | Utility-first styling |
| Mapbox GL JS | 3.7 | Satellite globe & map rendering |
| DM Mono + Syne | — | UI typography (Google Fonts) |

**Backend (planned — Phase 2)**
| Component | Technology |
|---|---|
| API server | FastAPI (Python) |
| Spatial processing | GeoPandas |
| Machine learning | scikit-learn (Isolation Forest) |
| Earth observation | Google Earth Engine |

**Frontend Architecture**
```
src/
├── App.jsx                   # Root — state, layout, map container
├── main.jsx                  # React entry + CSS imports
├── constants/
│   ├── cities.js             # City coordinates, zones, map positions
│   └── layers.js             # Layer config, Mapbox token loader
├── hooks/
│   └── index.js              # useClock, useToast, useIntro, useMapbox
├── utils/
│   └── helpers.js            # getSeverityColor, generateTrend, buildGeoJSON
├── styles/
│   └── globals.css           # CSS variables, keyframe animations
└── components/
    ├── map/
    │   └── IntroOverlay.jsx   # Satellite boot screen splash
    ├── panels/
    │   ├── TopBar.jsx         # Header — wordmark + REC clock + coords
    │   ├── LayerControls.jsx  # Data layer toggles + parameter sliders
    │   ├── InsightPanel.jsx   # Zone analysis slide-in panel
    │   └── BottomBar.jsx      # Severity legend + city selector
    ├── hud/
    │   ├── HUDCorners.jsx     # Surveillance-style corner brackets
    │   ├── StatusBar.jsx      # Bottom system status strip
    │   └── Toast.jsx          # Timed notification toast
    └── ui/
        ├── TrendSparkline.jsx # SVG animated sparkline
        └── RootCauseBar.jsx   # Progress bar for root-cause breakdown
```

---

## 📈 Research Scope

GeoSense establishes a foundation for:

- Multi-indicator ecological monitoring
- Urban sustainability analytics
- Spatial anomaly detection research
- Environmental risk modeling

Future phases may incorporate advanced ensemble models and temporal trend analysis.

---

## Quick Start

```bash
# Install dependencies
npm install

# Copy env template and add your Mapbox token
# Windows:  copy .env.example .env
# Mac/Linux: cp .env.example .env

# Start dev server → http://localhost:5173
npm run dev

# Production build
npm run build
```

> **Note:** Get a free Mapbox token at [account.mapbox.com](https://account.mapbox.com) and set it as `VITE_MAPBOX_TOKEN` in `.env`. The `.env` file is git-ignored — never commit your real token.
