# Bugfix Requirements Document

## Introduction

The GeoSense API endpoint `/api/metrics/latest` returns environmental data for ~189 grid cells covering Mumbai, but the data exhibits widespread null values across satellite-derived metrics (NDVI, NDWI, LST), air quality components (PM2.5, PM10, NO2), and weather data (temperature, humidity). Additionally, many zones show uniform AQI values (e.g., AQI=65) with `aqi_source_type: "estimated"`. 

Investigation reveals that the data ingestion pipeline consists of well-structured scripts for fetching data from AQICN (air quality stations), Google Earth Engine Sentinel-2 (NDVI/NDWI), and Landsat 8/9 (LST). However, **these ingestion scripts are not being executed automatically**. The codebase includes a scheduler (`server/scripts/scheduler.py`) that orchestrates periodic data ingestion, but this scheduler is **not invoked from the FastAPI application startup** (`app/main.py`). As a result, the database contains either stale data from manual script execution or null values where no data has been ingested.

The bug impacts data quality, user trust, and the entire analytical pipeline that depends on recent environmental observations.

## Bug Analysis

### Current Behavior (Defect)

**Section 1: Ingestion Pipeline Execution**

1.1 WHEN the FastAPI application starts THEN the system does not execute any data ingestion scripts

1.2 WHEN the FastAPI application is running THEN the system does not schedule or trigger periodic data ingestion for AQICN, Sentinel-2, or Landsat sources

1.3 WHEN `/api/metrics/latest` is called THEN the system returns whatever data exists in the database, regardless of staleness or completeness

**Section 2: Data Quality in API Responses**

1.4 WHEN grid zones lack recent satellite observations THEN the system returns `ndvi: null`, `ndwi: null`, `lst: null` without indicating data staleness

1.5 WHEN grid zones lack air quality component data THEN the system returns `pm25: null`, `pm10: null`, `no2: null` even if AQI values exist

1.6 WHEN grid zones have only IDW-estimated AQI values THEN the system may return uniform estimates (e.g., AQI=65) that appear suspicious but are mathematically valid IDW interpolations from distant stations

1.7 WHEN weather data (temperature, humidity) is requested THEN the system hardcodes `temperature: null` and `humidity: null` in the API route without attempting retrieval

### Expected Behavior (Correct)

**Section 2: Automated Ingestion Pipeline**

2.1 WHEN the FastAPI application starts THEN the system SHALL provide a mechanism to initiate or signal the availability of the scheduler for periodic data ingestion

2.2 WHEN the scheduler runs THEN the system SHALL execute AQICN ingestion every 3 hours using `run_aqi_cycle()`

2.3 WHEN the scheduler runs THEN the system SHALL execute Sentinel-2 NDVI/NDWI ingestion every 7 days using a 14-day composite window

2.4 WHEN the scheduler runs THEN the system SHALL execute Landsat LST ingestion every 14 days using a 45-day composite window

2.5 WHEN both satellite sources (Sentinel-2 and Landsat) complete successfully on the same UTC date along with AQI data THEN the system SHALL trigger the feature anomaly detection pipeline

2.6 WHEN any ingestion script encounters an error THEN the system SHALL log the error with sufficient detail for debugging while continuing to attempt subsequent scheduled runs

**Section 3: Data Quality and Transparency**

2.7 WHEN satellite data ingestion scripts execute successfully THEN the system SHALL persist non-null NDVI, NDWI, and LST values to the database with appropriate `observed_at` timestamps

2.8 WHEN AQICN ingestion executes successfully THEN the system SHALL persist AQI and available air quality components (PM2.5, PM10, NO2) with correct `aqi_source_type` marking ("observed" for direct station measurements, "estimated" for IDW-interpolated values)

2.9 WHEN cloud masking or data quality filters remove all valid satellite pixels for a zone THEN the system SHALL persist null values honestly without fabricating measurements

2.10 WHEN the API returns environmental metrics THEN the system SHALL include the actual values from the database without hardcoding null values in the route handler

2.11 WHEN weather data (temperature, humidity) sources are not yet implemented THEN the system SHALL return null values honestly, indicating unavailable data sources

### Unchanged Behavior (Regression Prevention)

**Section 3: Existing Data Integrity**

3.1 WHEN ingestion scripts use upsert operations with `ON CONFLICT (zone_id, observed_at)` THEN the system SHALL CONTINUE TO update only the specific columns managed by that script without overwriting other environmental metrics

3.2 WHEN NDVI/NDWI ingestion runs THEN the system SHALL CONTINUE TO preserve existing AQI, LST, and other non-Sentinel-2 metrics for the same zone and timestamp

3.3 WHEN AQI ingestion runs THEN the system SHALL CONTINUE TO preserve existing satellite-derived metrics (NDVI, NDWI, LST) for the same zone and timestamp

3.4 WHEN LST ingestion runs THEN the system SHALL CONTINUE TO preserve existing AQI and Sentinel-2 metrics for the same zone and timestamp

**Section 4: Test Suite and Architecture**

3.5 WHEN bugfix changes are applied THEN the system SHALL CONTINUE TO pass all 76 existing tests without regression

3.6 WHEN ingestion scripts execute THEN the system SHALL CONTINUE TO use the existing bug condition methodology: honest null values when data is unavailable, never fabricating environmental measurements

3.7 WHEN the database schema is accessed THEN the system SHALL CONTINUE TO maintain the `zones` table structure and `environment_data` unique constraint on `(zone_id, observed_at)`

3.8 WHEN Google Earth Engine operations are performed THEN the system SHALL CONTINUE TO use service account authentication and avoid downloading raster imagery

**Section 5: API Contracts**

3.9 WHEN `/api/metrics/latest` is called THEN the system SHALL CONTINUE TO return the latest observation timestamp across all zones with the established JSON response format

3.10 WHEN `/api/metrics/{locality_id}` is called THEN the system SHALL CONTINUE TO return time series data for the specified zone over the requested time window

3.11 WHEN `/api/anomalies` is called THEN the system SHALL CONTINUE TO return detected anomalies with their evidence and explanation

3.12 WHEN clients consume API responses THEN the system SHALL CONTINUE TO use the same field names and data types (e.g., `aqi` as integer, `ndvi` as float, `date` as ISO8601 timestamp)
