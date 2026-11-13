"""Ingest AQI proxy for GeoSense zones using Sentinel-5P NO2.

Pipeline:
- Load existing zones from PostGIS.
- Query Sentinel-5P NO2 collection over the zone extent.
- Build median composite across a recent window.
- Compute zonal mean NO2 for all zones via reduceRegions.
- Scale NO2 density to a 0-500 proxy AQI score.
- Atomic upsert into environment_data (zone_id, observed_at) with aqi.
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict

import ee
from sqlalchemy import text

from app.database import get_db
from app.services.source_metadata import ensure_compatible_metadata, metadata_payload
from gee.gee_client import initialize_ee

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

S5P_DATASET = "COPERNICUS/S5P/NRTI/L3_NO2"
COMPOSITE_WINDOW_DAYS = 14
MAX_NO2_PROXY = 0.0002

def fetch_cells_as_fc(db) -> ee.FeatureCollection:
    rows = db.execute(text("SELECT id, ST_AsGeoJSON(geometry) AS geojson FROM zones"))
    features = []
    for row in rows:
        zid = int(row[0])
        geom = json.loads(row[1])
        features.append(ee.Feature(geom, {"zone_id": zid}))
    return ee.FeatureCollection(features)

def add_aqi_proxy(image: ee.Image) -> ee.Image:
    # Scale NO2 tropospheric column to 0-500 AQI proxy
    no2 = image.select("tropospheric_NO2_column_number_density")
    # Clamp negative noise to 0, then scale
    aqi_proxy = no2.max(0).divide(MAX_NO2_PROXY).multiply(500.0).rename("AQI")
    return image.addBands(aqi_proxy)

def source_context(start_date: str, end_date: str) -> dict:
    start = datetime.fromisoformat(start_date).date()
    end = datetime.fromisoformat(end_date).date()
    if (end - start).days != COMPOSITE_WINDOW_DAYS:
        raise ValueError(
            f"AQI history uses a fixed {COMPOSITE_WINDOW_DAYS}-day composite window"
        )
    return {
        "dataset": S5P_DATASET,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "window_days": COMPOSITE_WINDOW_DAYS,
        "composite": "median",
        "scale_m": 1113.2,
        "band": "tropospheric_NO2_column_number_density",
        "aqi_proxy_conversion": f"max(0, NO2) / {MAX_NO2_PROXY} * 500.0",
    }

def run_ingest(start_date: str, end_date: str) -> Dict:
    context = source_context(start_date, end_date)
    initialize_ee()
    observed_at = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)

    with get_db() as db:
        cells_fc = fetch_cells_as_fc(db)

        collection = (
            ee.ImageCollection(S5P_DATASET)
            .filterDate(start_date, end_date)
            .filterBounds(cells_fc.geometry())
        )

        image_count = int(collection.size().getInfo())

        processed_coll = collection.map(add_aqi_proxy)

        features = []
        if image_count > 0:
            composite = processed_coll.median()
            band_count = int(composite.bandNames().size().getInfo())
            if band_count > 0:
                reduced = composite.select(["AQI"]).reduceRegions(
                    collection=cells_fc,
                    reducer=ee.Reducer.mean(),
                    scale=1113.2,
                )
                features = reduced.getInfo().get("features", [])

        zones_processed = 0
        valid_aqi = 0
        for feat in features:
            props = feat.get("properties", {})
            zid = int(props["zone_id"])
            aqi = props.get("mean") if props.get("mean") is not None else props.get("AQI")
            aqi_val = float(aqi) if aqi is not None else None
            if aqi_val is not None:
                # clamp to max 500
                aqi_val = min(500.0, max(0.0, aqi_val))
                valid_aqi += 1

            metadata_context = context if aqi_val is not None else None
            ensure_compatible_metadata(
                db,
                zone_id=zid,
                observed_at=observed_at,
                key="aqi",
                context=metadata_context,
            )

            db.execute(
                text(
                    """
                    INSERT INTO environment_data (cell_id, observed_at, aqi, source_metadata)
                    VALUES (:z, :obs, :aqi, CAST(:metadata AS jsonb))
                    ON CONFLICT (cell_id, observed_at)
                    DO UPDATE SET
                        aqi = EXCLUDED.aqi,
                        source_metadata = environment_data.source_metadata || EXCLUDED.source_metadata
                    """
                ),
                {
                    "z": zid,
                    "obs": observed_at,
                    "aqi": aqi_val,
                    "metadata": metadata_payload("aqi", metadata_context),
                },
            )
            zones_processed += 1

        db.commit()

    return {
        "dataset": S5P_DATASET,
        "start_date": start_date,
        "end_date": end_date,
        "images_found": image_count,
        "zones_processed": zones_processed,
        "valid_aqi": valid_aqi,
        "null_aqi": zones_processed - valid_aqi,
    }

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=False, help="YYYY-MM-DD")
    p.add_argument("--end", required=False, help="YYYY-MM-DD")
    p.add_argument("--days", type=int, default=COMPOSITE_WINDOW_DAYS, help="Fixed composite window length")
    return p.parse_args()

def main() -> int:
    args = parse_args()
    today = datetime.now(timezone.utc).date()
    end = datetime.fromisoformat(args.end).date() if args.end else today
    start = datetime.fromisoformat(args.start).date() if args.start else (end - timedelta(days=args.days))

    try:
        report = run_ingest(start.isoformat(), end.isoformat())
        logger.info("AQI ingest report: %s", report)
        return 0
    except Exception as exc:
        logger.exception("AQI ingest failed: %s", exc)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
