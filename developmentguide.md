GeoSense Project Context & Development Guidelines

You are assisting in the development of GeoSense, an AI-powered environmental monitoring and analysis platform. Before making any code changes, understand the architecture and constraints below and strictly follow them.

Project Goal

GeoSense monitors environmental conditions of a city (starting with Mumbai) by combining satellite imagery and AQI data to detect anomalies, visualize environmental conditions on an interactive heatmap, and provide insights.

This project is being built in phases. We are currently implementing the core system and must avoid unnecessary complexity.

Current Technology Stack

Frontend

React
Mapbox GL JS

Backend

FastAPI (Python)

Database

PostgreSQL
PostGIS
Running inside Docker

Machine Learning

scikit-learn
Isolation Forest (Phase 1)
XGBoost (later phase)

Data Sources

Google Earth Engine
Sentinel-2 (NDVI & NDWI)
Landsat 8 + Landsat 9 (LST)
AQICN API (AQI)
Data Pipeline

Google Earth Engine
↓
Python Extraction Scripts
↓
PostgreSQL + PostGIS
↓
FastAPI APIs
↓
React Frontend

The frontend must never communicate directly with Google Earth Engine or external APIs.

Everything should go through FastAPI.

Update Frequency

AQI

Updated hourly from AQICN API

NDVI

Updated weekly using Sentinel-2

NDWI

Updated weekly using Sentinel-2

LST

Updated using the latest available Landsat 8/9 imagery (approximately every 8–16 days)

These values are stored in PostgreSQL and served by FastAPI.

Heatmap

We are NOT creating raster tiles.

We will generate a smooth gradient heatmap using approximately 150–200 grid points across Mumbai.

Google Earth Engine will compute environmental metrics for each grid cell.

The frontend will visualize those values using Mapbox heatmap layers.

Feature Engineering

Raw metrics:

AQI
NDVI
NDWI
LST

Derived features include:

Daily differences
Rolling averages
Trend indicators
Pollution Risk
Heat Stress
Water Stress

These engineered features are inputs for Isolation Forest.

Machine Learning

Phase 1

Isolation Forest for anomaly detection.

Phase 2

XGBoost for identifying feature importance and likely root causes.

Future

RAG-based environmental explanations.

Do NOT introduce deep learning or unnecessary AI models.

Database

We will use PostgreSQL + PostGIS only.

Do NOT introduce:

Firebase
MongoDB
Supabase
Azure Blob Storage
Cloudflare
Redis
Kafka
RabbitMQ

unless explicitly requested.

Backend Principles

Keep the backend simple.

Avoid enterprise patterns that are unnecessary for this project.

Do not generate excessive abstraction layers.

Only create what is needed.

Prefer:

app/
api/
models/
schemas/
services/
database.py
main.py

over overly complex architectures.

Development Style

Work incrementally.

Each feature should be fully functional before moving to the next.

Do not implement future features unless requested.

Do not refactor unrelated code.

Do not replace working implementations.

When uncertain, ask before making architectural changes.

Current Task

The project previously used dummy data.

Before implementing new functionality:

Identify all dummy data.
Remove or isolate it cleanly.
Replace it with a proper backend-driven architecture.
Preserve the existing frontend UI.
Keep components reusable.

Do not break the current UI.

Goal

Build GeoSense as a clean, modular, production-quality project while keeping the architecture simple, maintainable, and scalable. Prioritize correctness, readability, and stability over unnecessary complexity.