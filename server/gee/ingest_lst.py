"""Ingest LST for GeoSense zones using Landsat 8/9 Collection 2 Level-2.

Pipeline:
- Load existing zones from PostGIS.
- Query Landsat 8 + Landsat 9 L2 collections over the zone extent.
- Apply QA_PIXEL cloud/shadow masking.
- Convert ST_B10 to Celsius using USGS scale/offset.
- Build median composite across a recent window.
- Compute zonal mean LST for all zones via reduceRegions.
- Atomic upsert into environment_data (zone_id, observed_at) with lst only.

Notes:
- No raster downloads.
- No schema changes.
- Idempotent via ON CONFLICT on (zone_id, observed_at).
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

LST_DATASETS = ("LANDSAT/LC08/C02/T1_L2", "LANDSAT/LC09/C02/T1_L2")
COMPOSITE_WINDOW_DAYS = 45


def fetch_cells_as_fc(db) -> ee.FeatureCollection:
    rows = db.execute(text("SELECT id, ST_AsGeoJSON(geometry) AS geojson FROM zones"))
    features = []
    for row in rows:
        zid = int(row[0])
        geom = json.loads(row[1])
        features.append(ee.Feature(geom, {"zone_id": zid}))
    return ee.FeatureCollection(features)


def mask_landsat_l2(image: ee.Image) -> ee.Image:
    # QA_PIXEL bits (Landsat C2): 0=fill, 3=cloud, 4=cloud shadow
    # Keep masking conservative but not overly strict to retain usable thermal pixels.
    qa = image.select("QA_PIXEL")
    clear = (
        qa.bitwiseAnd(1 << 0).eq(0)
        .And(qa.bitwiseAnd(1 << 3).eq(0))
        .And(qa.bitwiseAnd(1 << 4).eq(0))
    )
    return image.updateMask(clear)


def add_lst_celsius(image: ee.Image) -> ee.Image:
    # Landsat C2 L2 ST_B10: Kelvin = DN * 0.00341802 + 149.0
    # Celsius = Kelvin - 273.15
    lst_c = image.select("ST_B10").multiply(0.00341802).add(149.0).subtract(273.15).rename("LST")
    return image.addBands(lst_c)


def source_context(start_date: str, end_date: str) -> dict:
    start = datetime.fromisoformat(start_date).date()
    end = datetime.fromisoformat(end_date).date()
    if (end - start).days != COMPOSITE_WINDOW_DAYS:
        raise ValueError(
            f"LST history uses the existing fixed {COMPOSITE_WINDOW_DAYS}-day composite window; "
            f"received {start_date} to {end_date}"
        )
    return {
        "datasets": list(LST_DATASETS),
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "window_days": COMPOSITE_WINDOW_DAYS,
        "composite": "median",
        "scale_m": 30,
        "thermal_band": "ST_B10",
        "unit": "celsius",
        "qa_mask": "QA_PIXEL bits 0, 3, and 4",
        "temperature_conversion": "ST_B10 * 0.00341802 + 149.0 - 273.15",
    }


def run_ingest(start_date: str, end_date: str) -> Dict:
    context = source_context(start_date, end_date)
    initialize_ee()
    observed_at = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)

    with get_db() as db:
        cells_fc = fetch_cells_as_fc(db)

        l8 = (
            ee.ImageCollection(LST_DATASETS[0])
            .filterDate(start_date, end_date)
            .filterBounds(cells_fc.geometry())
        )
        l9 = (
            ee.ImageCollection(LST_DATASETS[1])
            .filterDate(start_date, end_date)
            .filterBounds(cells_fc.geometry())
        )

        merged = l8.merge(l9)
        image_count = int(merged.size().getInfo())

        processed_coll = merged.map(mask_landsat_l2).map(add_lst_celsius)

        features = []
        if image_count > 0:
            composite = processed_coll.median()
            band_count = int(composite.bandNames().size().getInfo())
            if band_count > 0:
                reduced = composite.select(["LST"]).reduceRegions(
                    collection=cells_fc,
                    reducer=ee.Reducer.mean(),
                    scale=30,
                )
                features = reduced.getInfo().get("features", [])
            else:
                logger.warning("LST composite has no valid bands after masking; writing NULL LST values.")

        if not features:
            # No usable imagery in window: write null LST values (no fabrication)
            features = zones_fc.getInfo().get("features", [])

        zones_processed = 0
        valid_lst = 0
        for feat in features:
            props = feat.get("properties", {})
            zid = int(props["zone_id"])
            # For single-band reduceRegions + mean reducer, EE typically returns 'mean'.
            lst = props.get("mean") if props.get("mean") is not None else props.get("LST")
            lst_val = float(lst) if lst is not None else None
            if lst_val is not None:
                valid_lst += 1

            metadata_context = context if lst_val is not None else None
            ensure_compatible_metadata(
                db,
                zone_id=zid,
                observed_at=observed_at,
                key="lst",
                context=metadata_context,
            )

            db.execute(
                text(
                    """
                    INSERT INTO environment_data (cell_id, observed_at, lst, source_metadata)
                    VALUES (:c, :obs, :lst, CAST(:metadata AS jsonb))
                    ON CONFLICT (cell_id, observed_at)
                    DO UPDATE SET
                        lst = EXCLUDED.lst,
                        source_metadata = environment_data.source_metadata || EXCLUDED.source_metadata
                    """
                ),
                {
                    "z": zid,
                    "obs": observed_at,
                    "lst": lst_val,
                    "metadata": metadata_payload("lst", metadata_context),
                },
            )
            zones_processed += 1

        db.commit()

    return {
        "dataset": " + ".join(LST_DATASETS),
        "start_date": start_date,
        "end_date": end_date,
        "images_found": image_count,
        "zones_processed": zones_processed,
        "valid_lst": valid_lst,
        "null_lst": zones_processed - valid_lst,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=False, help="YYYY-MM-DD")
    p.add_argument("--end", required=False, help="YYYY-MM-DD")
    p.add_argument("--days", type=int, default=COMPOSITE_WINDOW_DAYS, help="Fixed composite window length (must be 45)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    today = datetime.now(timezone.utc).date()
    end = datetime.fromisoformat(args.end).date() if args.end else today
    start = datetime.fromisoformat(args.start).date() if args.start else (end - timedelta(days=args.days))

    try:
        report = run_ingest(start.isoformat(), end.isoformat())
        logger.info("LST ingest report: %s", report)
        return 0
    except Exception as exc:
        logger.exception("LST ingest failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
