import sys, os
sys.path.insert(0, os.getcwd())
import logging
logging.basicConfig(level=logging.INFO)

print("Starting NDVI ingest...")
from gee.ingest_ndvi_ndwi import run_ingest as run_ndvi
res_ndvi = run_ndvi(start_date="2026-08-30", end_date="2026-09-13")
print("NDVI Result:", res_ndvi)

print("\nStarting LST ingest...")
from gee.ingest_lst import run_ingest as run_lst
res_lst = run_lst(start_date="2026-07-02", end_date="2026-08-16")
print("LST Result:", res_lst)

print("\nStarting OpenAQ AQI ingest...")
from openaq.derive_aqi_grid import run_openaq_derivation
res_aqi = run_openaq_derivation()
print("AQI Result:", res_aqi)

print("\nRunning Anomaly pipeline...")
from app.services.feature_anomaly_pipeline import run_feature_anomaly_pipeline
from datetime import datetime, timezone
# Run for the latest snapshot (today)
res_ml = run_feature_anomaly_pipeline()
print("ML Result:", res_ml)
