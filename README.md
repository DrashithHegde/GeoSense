# GeoSense
GeoSense monitors urban environmental health using satellite-derived indicators such as NDVI (vegetation health), NDWI (surface water presence), Land Surface Temperature (LST), and National Air Quality Index (AQI). It detects abnormal spatial patterns across city zones to highlight emerging environmental stress and ecological risk.
=======
🌍 GeoSense: Spatial Environmental Anomaly Detection Framework

GeoSense is a research-oriented environmental intelligence framework designed to detect spatial ecological anomalies in urban regions using multi-indicator satellite-derived features and air quality metrics.

The system integrates vegetation health (NDVI), surface water presence (NDWI), Land Surface Temperature (LST), and National Air Quality Index (AQI) to model environmental stress patterns and identify abnormal spatial behavior across city zones.

📌 Research Motivation

Urban ecosystems are increasingly impacted by:

Vegetation degradation

Surface water depletion

Urban heat island intensification

Rising atmospheric pollution

Existing monitoring systems typically evaluate these indicators independently. GeoSense proposes a multi-dimensional spatial anomaly detection approach to identify compounded environmental stress signals.

🧠 Methodological Overview

GeoSense follows a structured environmental analytics pipeline:

Spatial Zoning

Urban areas are partitioned into geographic zones.

Each zone represents a spatial unit for analysis.

Feature Extraction

NDVI → Vegetation health

NDWI → Surface water presence

LST → Surface heat distribution

AQI → Air pollution intensity

Feature Normalization

Environmental indicators are scaled to ensure comparability.

Anomaly Detection (Phase 1)

Isolation Forest is applied to detect spatial outliers.

Zones with abnormal environmental feature combinations are flagged.

📊 Environmental Indicators
NDVI (Normalized Difference Vegetation Index)

Quantifies vegetation density and vitality.
Lower NDVI values may indicate vegetation stress or land degradation.

NDWI (Normalized Difference Water Index)

Measures surface water presence and moisture variability.
Useful for detecting shrinking water bodies or hydrological stress.

LST (Land Surface Temperature)

Derived from thermal satellite data.
Used to identify heat concentration and urban heat islands.

AQI (Air Quality Index)

Represents aggregated air pollutant concentration levels.
Higher values indicate deteriorating atmospheric conditions.

🔍 Spatial Anomaly Modeling

GeoSense does not rely on threshold-based classification.

Instead, it evaluates multi-feature environmental behavior across zones and detects statistically rare patterns. An anomaly may represent:

Concurrent vegetation decline and heat increase

Water body reduction with rising AQI

Abnormal environmental combinations relative to neighboring zones

This enables early detection of emerging ecological risk clusters.

🗺️ Visualization Layer

The system presents:

Zone-based spatial heatmaps

Gradient environmental intensity mapping

Clear anomaly highlighting

Minimal, research-focused geographic interface

Visualization emphasizes interpretability over visual clutter.

🛠️ Technical Framework (Phase 1)

Frontend: React + Interactive Map Interface

Backend: Node.js + Express

Database: MongoDB

Spatial Processing: GeoPandas

Machine Learning: scikit-learn (Isolation Forest)

📈 Research Scope

GeoSense establishes a foundation for:

Multi-indicator ecological monitoring

Urban sustainability analytics

Spatial anomaly detection research

Environmental risk modeling

Future phases may incorporate advanced ensemble models and temporal trend analysis.

