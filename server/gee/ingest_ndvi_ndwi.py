"""Ingest NDVI, NDWI, and Water Health signals from Sentinel-2.

Usage:
    python -m server.gee.ingest_ndvi_ndwi --start YYYY-MM-DD --end YYYY-MM-DD

Default window: last 14 days (end = today, start = today - 14).

Behavior:
- Loads zones from PostGIS using `get_db()`.
- Converts zones to an Earth Engine FeatureCollection.
- Filters COPERNICUS/S2_SR_HARMONIZED to the window and area.
- Applies the project's established Sentinel-2 QA60 cloud filtering approach.
- Adds NDVI, NDWI, MNDWI, NDCI proxy, and turbidity proxy bands per image.
- Computes a median composite for the fixed window.
- Runs `reduceRegions` with `ee.Reducer.mean()` to get per-zone means.
- Upserts raw observation values into `environment_data` using `observed_at` = end_date (UTC).

Idempotency: Uses `zone_id` + `observed_at` unique constraint — the script will
update existing rows for the same `observed_at` rather than inserting duplicates.

Safety: Does not download images or modify zones table.
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import ee
from sqlalchemy import text

from app.database import get_db
from app.models import EnvironmentData
from app.services.source_metadata import ensure_compatible_metadata, metadata_payload
from gee.gee_client import initialize_ee

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

S2_DATASET = "COPERNICUS/S2_SR_HARMONIZED"
COMPOSITE_WINDOW_DAYS = 14
DEFAULT_MNDWI_THRESHOLD = 0.0


def calculate_mndwi(green: float | None, shortwave_ir: float | None) -> float | None:
    """MNDWI = (B3 - B11) / (B3 + B11)."""
    if green is None or shortwave_ir is None:
        return None
    denominator = green + shortwave_ir
    if denominator == 0:
        return None
    return float((green - shortwave_ir) / denominator)


def water_health_applicable(mndwi: float | None, threshold: float = DEFAULT_MNDWI_THRESHOLD) -> bool:
    """True only when a location is detected as water under the configured MNDWI threshold."""
    return mndwi is not None and mndwi >= threshold


def calculate_ndci_proxy(red_edge: float | None, red: float | None) -> float | None:
    """Sentinel-2 algal/chlorophyll-related spectral proxy: (B5 - B4) / (B5 + B4)."""
    if red_edge is None or red is None:
        return None
    denominator = red_edge + red
    if denominator == 0:
        return None
    return float((red_edge - red) / denominator)


def calculate_turbidity_proxy(green: float | None, red: float | None) -> float | None:
    """Relative suspended-material proxy based on green/red contrast, not NTU."""
    if green is None or red is None:
        return None
    denominator = green + red
    if denominator == 0:
        return None
    return float((green - red) / denominator)


def calculate_water_health_score(
    *,
    mndwi: float | None,
    ndci: float | None,
    turbidity_proxy: float | None,
    prior_change_pct: float | None,
    anomaly_score: float | None,
    water_threshold: float = DEFAULT_MNDWI_THRESHOLD,
) -> float | None:
    """Explainable Water Health score for detected water only.

    The score is a 0..1 condition score where higher means better condition. It is
    a relative early-warning indicator and intentionally does not treat more water
    as automatically healthier. Missing values remain missing.
    """
    if not water_health_applicable(mndwi, threshold=water_threshold):
        return None

    if all(value is None for value in (ndci, turbidity_proxy, prior_change_pct, anomaly_score)):
        return None

    health_components: list[float] = []
    if ndci is not None:
        algal_stress = max(0.0, min(1.0, (ndci + 1.0) / 2.0))
        health_components.append(1.0 - algal_stress)
    if turbidity_proxy is not None:
        suspended_material_stress = max(0.0, min(1.0, (turbidity_proxy + 1.0) / 2.0))
        health_components.append(1.0 - suspended_material_stress)
    if prior_change_pct is not None:
        deterioration_stress = max(0.0, min(1.0, abs(min(0.0, prior_change_pct))))
        health_components.append(1.0 - deterioration_stress)
    if anomaly_score is not None:
        health_components.append(1.0 - max(0.0, min(1.0, anomaly_score)))

    if not health_components:
        return None
    return float(max(0.0, min(1.0, sum(health_components) / len(health_components))))


def fetch_cells_as_feature_collection(db) -> ee.FeatureCollection:
    # Pull zones as GeoJSON from PostGIS
    sql = text("SELECT id, ST_AsGeoJSON(geometry) AS geojson FROM spatial_cells;")
    result = db.execute(sql)
    features = []
    for row in result:
        cell_id = int(row[0])
        geojson_text = row[1]
        geom = json.loads(geojson_text)
        props = {"cell_id": cell_id}
        feat = ee.Feature(geom, props)
        features.append(feat)
    fc = ee.FeatureCollection(features)
    return fc


def mask_s2_sr(image: ee.Image) -> ee.Image:
    # QA60 cloud mask: bits 10 (cloud) and 11 (cirrus)
    qa = image.select("QA60")
    cloudBitMask = 1 << 10
    cirrusBitMask = 1 << 11
    mask = qa.bitwiseAnd(cloudBitMask).eq(0).And(qa.bitwiseAnd(cirrusBitMask).eq(0))
    return image.updateMask(mask)


def add_indices(image: ee.Image) -> ee.Image:
    # Sentinel-2 bands: B3=green, B4=red, B5=red-edge, B8=NIR, B11=SWIR
    ndvi = image.normalizedDifference(["B8", "B4"]).rename("NDVI")
    ndwi = image.normalizedDifference(["B3", "B8"]).rename("NDWI")
    mndwi = image.normalizedDifference(["B3", "B11"]).rename("MNDWI")
    ndci = image.normalizedDifference(["B5", "B4"]).rename("NDCI_PROXY")
    turbidity = image.normalizedDifference(["B3", "B4"]).rename("TURBIDITY_PROXY")
    return image.addBands([ndvi, ndwi, mndwi, ndci, turbidity])


def source_context(start_date: str, end_date: str) -> dict:
    start = datetime.fromisoformat(start_date).date()
    end = datetime.fromisoformat(end_date).date()
    if (end - start).days != COMPOSITE_WINDOW_DAYS:
        raise ValueError(
            f"NDVI/NDWI history uses a fixed {COMPOSITE_WINDOW_DAYS}-day composite window; "
            f"received {start_date} to {end_date}"
        )
    return {
        "dataset": S2_DATASET,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "window_days": COMPOSITE_WINDOW_DAYS,
        "composite": "median",
        "scale_m": 10,
        "cloud_mask": "project-established QA60-cloud filtering with cirrus exclusion",
        "indices": {
            "ndvi": "normalizedDifference(B8,B4)",
            "ndwi": "normalizedDifference(B3,B8)",
            "mndwi": "normalizedDifference(B3,B11)",
            "ndci_proxy": "normalizedDifference(B5,B4)",
            "turbidity_proxy": "normalizedDifference(B3,B4)",
        },
        "mndwi_threshold": DEFAULT_MNDWI_THRESHOLD,
    }


def run_ingest(start_date: str, end_date: str, cloud_threshold: Optional[float] = None) -> Dict:
    context = source_context(start_date, end_date)
    initialize_ee()

    # Use end_date as observed_at timestamp (UTC, midnight)
    observed_at = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)

    with get_db() as db:
        cells_fc = fetch_cells_as_feature_collection(db)

        # Filter S2 harmonized
        collection = (
            ee.ImageCollection(S2_DATASET)
            .filterDate(start_date, end_date)
            .filterBounds(cells_fc.geometry())
        )

        n_images = int(collection.size().getInfo())
        logger.info("Images found in window: %s", n_images)

        if n_images == 0:
            logger.warning("No Sentinel-2 images found in the given window.")

        # Apply QA mask and compute indices per image
        collection = collection.map(mask_s2_sr).map(add_indices)

        # Median composite
        composite = collection.median().select(["NDVI", "NDWI", "MNDWI", "NDCI_PROXY", "TURBIDITY_PROXY"])

        # Reduce over the feature collection (zones)
        reducer = ee.Reducer.mean()
        reduced = composite.reduceRegions(collection=cells_fc, reducer=reducer, scale=10)

        water_extent_reduced = (
            ee.Image.pixelArea()
            .updateMask(composite.select("MNDWI").gte(DEFAULT_MNDWI_THRESHOLD))
            .reduceRegions(collection=cells_fc, reducer=ee.Reducer.sum(), scale=10)
        )

        water_extent_lookup = {
            int(feature["properties"].get("zone_id")): float(feature["properties"].get("sum", 0.0))
            for feature in water_extent_reduced.getInfo().get("features", [])
            if feature.get("properties", {}).get("zone_id") is not None
        }

        # Get results
        features = reduced.getInfo().get("features", [])

        processed = 0
        ndvi_count = 0
        ndwi_count = 0
        mndwi_count = 0
        ndci_count = 0
        turbidity_count = 0
        water_extent_count = 0
        water_health_score_count = 0

        for feat in features:
            props = feat.get("properties", {})
            zone_id = props.get("zone_id")
            # reduceRegions produced band keys 'NDVI' and 'NDWI' (median composite values)
            ndvi = props.get("NDVI")
            ndwi = props.get("NDWI")
            mndwi = props.get("MNDWI")
            ndci = props.get("NDCI_PROXY")
            turbidity = props.get("TURBIDITY_PROXY")

            # Normalize to float or None
            ndvi_val = float(ndvi) if ndvi is not None else None
            ndwi_val = float(ndwi) if ndwi is not None else None
            mndwi_val = float(mndwi) if mndwi is not None else None
            ndci_val = float(ndci) if ndci is not None else None
            turbidity_val = float(turbidity) if turbidity is not None else None

            if ndvi_val is not None:
                ndvi_count += 1
            if ndwi_val is not None:
                ndwi_count += 1
            if mndwi_val is not None:
                mndwi_count += 1
            if ndci_val is not None:
                ndci_count += 1
            if turbidity_val is not None:
                turbidity_count += 1

            water_applicable = water_health_applicable(mndwi_val, threshold=DEFAULT_MNDWI_THRESHOLD)
            water_extent_m2 = water_extent_lookup.get(zone_id)
            if water_extent_m2 is not None and not water_applicable:
                water_extent_m2 = None

            water_score = calculate_water_health_score(
                mndwi=mndwi_val,
                ndci=ndci_val,
                turbidity_proxy=turbidity_val,
                prior_change_pct=None,
                anomaly_score=None,
                water_threshold=DEFAULT_MNDWI_THRESHOLD,
            )
            water_status = (
                "healthy" if water_score is not None and water_score >= 0.6 else "watch" if water_score is not None else None
            )
            if water_extent_m2 is not None:
                water_extent_count += 1
            if water_score is not None:
                water_health_score_count += 1

            metadata_context = context if any(value is not None for value in (ndvi_val, ndwi_val, mndwi_val, ndci_val, turbidity_val, water_extent_m2, water_score)) else None
            ensure_compatible_metadata(
                db,
                cell_id=cell_id,
                observed_at=observed_at,
                key="ndvi_ndwi",
                context=metadata_context,
            )
            ensure_compatible_metadata(
                db,
                cell_id=cell_id,
                observed_at=observed_at,
                key="water_health",
                context=metadata_context,
            )

            # Atomic upsert: INSERT ... ON CONFLICT (cell_id, observed_at) DO UPDATE
            db.execute(
                text(
                    """
                    INSERT INTO environment_data (
                        cell_id, observed_at, ndvi, ndwi, mndwi, ndci, turbidity_proxy,
                        water_extent_m2, water_health_score, water_health_status, source_metadata
                    )
                    VALUES (
                        :c, :obs, :ndvi, :ndwi, :mndwi, :ndci, :turbidity_proxy,
                        :water_extent_m2, :water_health_score, :water_health_status, CAST(:metadata AS jsonb)
                    )
                    ON CONFLICT (cell_id, observed_at)
                    DO UPDATE SET
                        ndvi = EXCLUDED.ndvi,
                        ndwi = EXCLUDED.ndwi,
                        mndwi = EXCLUDED.mndwi,
                        ndci = EXCLUDED.ndci,
                        turbidity_proxy = EXCLUDED.turbidity_proxy,
                        water_extent_m2 = EXCLUDED.water_extent_m2,
                        water_health_score = EXCLUDED.water_health_score,
                        water_health_status = EXCLUDED.water_health_status,
                        source_metadata = environment_data.source_metadata || EXCLUDED.source_metadata
                    """
                ),
                {
                    "c": cell_id,
                    "obs": observed_at,
                    "ndvi": ndvi_val,
                    "ndwi": ndwi_val,
                    "mndwi": mndwi_val,
                    "ndci": ndci_val,
                    "turbidity_proxy": turbidity_val,
                    "water_extent_m2": water_extent_m2,
                    "water_health_score": water_score,
                    "water_health_status": water_status,
                    "metadata": json.dumps(
                        {
                            "ndvi_ndwi": metadata_context,
                            "water_health": metadata_context,
                        }
                        if metadata_context
                        else {}
                    ),
                },
            )

            processed += 1

        db.commit()

    report = {
        "start_date": start_date,
        "end_date": end_date,
        "n_images": n_images,
        "zones_processed": processed,
        "ndvi_count": ndvi_count,
        "ndwi_count": ndwi_count,
        "mndwi_count": mndwi_count,
        "ndci_count": ndci_count,
        "turbidity_count": turbidity_count,
        "water_extent_count": water_extent_count,
        "water_health_score_count": water_health_score_count,
    }
    return report


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--start", help="Start date YYYY-MM-DD", required=False)
    p.add_argument("--end", help="End date YYYY-MM-DD", required=False)
    p.add_argument("--days", type=int, default=COMPOSITE_WINDOW_DAYS, help="Fixed composite window length (must be 14)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    today = datetime.now(timezone.utc).date()
    if args.end:
        end = datetime.fromisoformat(args.end).date()
    else:
        end = today
    if args.start:
        start = datetime.fromisoformat(args.start).date()
    else:
        start = end - timedelta(days=args.days)

    start_str = start.isoformat()
    end_str = end.isoformat()

    logger.info("Running NDVI/NDWI ingest for window %s -> %s", start_str, end_str)
    try:
        report = run_ingest(start_str, end_str)
        logger.info("Ingest report: %s", report)
        return 0
    except Exception as e:
        logger.exception("Ingest failed: %s", e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
