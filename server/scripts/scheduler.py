"""Schedule the current GeoSense ingestion pipelines without fabricating history.

The AQI IDW job fetches OpenAQ observations itself, so legacy station-only
AQICN ingestion is intentionally not scheduled alongside it. This avoids
competing AQI records in ``environment_data`` while preserving diagnostic code.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import sys
import time


SERVER_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVER_ROOT.parent
for path in (str(REPO_ROOT), str(SERVER_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from app.services.feature_anomaly_pipeline import run_feature_anomaly_pipeline
from openaq.derive_aqi_grid import (
    collect_station_aqi_points,
    run_openaq_derivation as run_derivation,
)
from app.services.surfaces.aqi_surface import generate_aqi_surface
from gee.ingest_lst import COMPOSITE_WINDOW_DAYS as LST_WINDOW_DAYS
from gee.ingest_lst import run_ingest as run_lst_ingest
from app.services.surfaces.lst_surface import generate_lst_surface
from gee.ingest_ndvi_ndwi import COMPOSITE_WINDOW_DAYS as S2_WINDOW_DAYS
from gee.ingest_ndvi_ndwi import run_ingest as run_ndvi_ndwi_ingest
from app.services.surfaces.ndvi_surface import generate_ndvi_surface


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

AQI_INTERVAL = timedelta(hours=3)
S2_INTERVAL = timedelta(days=7)
LST_INTERVAL = timedelta(days=14)
POLL_SECONDS = 60


def run_aqi_cycle() -> dict:
    """Use one real OpenAQ station set for both the zone grid and AQI surface."""
    configuration = {
        "k": 4,
        "max_interp_distance_m": 15000.0,
        "min_stations": 2,
        "power": 2.0,
        "station_assign_distance_m": 8000,
    }
    station_points, stations_fetched, cpcb_failures = collect_station_aqi_points()
    derivation = run_derivation(
        **configuration,
        station_points=station_points,
        stations_fetched=stations_fetched,
        cpcb_aqi_failures=cpcb_failures,
    )
    # Derived surface failure must never invalidate the canonical raw/zone AQI
    # ingestion that already succeeded.  It is retried at the next AQI cycle.
    try:
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=14)
        surface = generate_aqi_surface(
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        )
        surface_result = {"generation_status": "generated", "png": surface["png_filename"]}
    except Exception as exc:
        logger.exception("AQI surface generation failed after successful AQI derivation")
        surface_result = {"generation_status": "failed", "error": str(exc)}
    return {"aqi_derivation": derivation, "aqi_surface": surface_result}


def _run_s2_for_today(today) -> dict:
    start = (today - timedelta(days=S2_WINDOW_DAYS)).isoformat()
    end = today.isoformat()
    ingestion = run_ndvi_ndwi_ingest(start, end)
    # The surface is a separate derived artifact from the same fixed-window
    # Sentinel-2 method; it never affects raw observations or frozen zones.
    try:
        surface = generate_ndvi_surface(start_date=start, end_date=end)
    except Exception as exc:
        logger.exception("NDVI surface generation failed after successful Sentinel-2 ingestion")
        surface = {"generation_status": "failed", "error": str(exc)}
    return {"ingestion": ingestion, "surface": surface}


def _run_lst_for_today(today) -> dict:
    start = (today - timedelta(days=LST_WINDOW_DAYS)).isoformat()
    end = today.isoformat()
    ingestion = run_lst_ingest(start, end)
    try:
        surface = generate_lst_surface(start, end)
    except Exception as exc:
        logger.exception("LST surface generation failed after successful Landsat ingestion")
        surface = {"generation_status": "failed", "error": str(exc)}
    return {"ingestion": ingestion, "surface": surface}


def describe_schedule() -> dict:
    return {
        "aqi_idw": "every 3 hours; this job fetches OpenAQ and derives the grid/surface",
        "sentinel_2_ndvi_ndwi": f"every 7 days using a fixed {S2_WINDOW_DAYS}-day composite",
        "landsat_lst": f"every 14 days using a fixed {LST_WINDOW_DAYS}-day composite",
        "feature_anomaly": "only after Sentinel-2 and Landsat both complete on the same UTC date",
        "excluded": "legacy station-only AQICN ingest, IMD, temporal analytics",
    }


def should_run_feature_pipeline(
    *,
    today,
    satellite_ready_date,
    aqi_ready_date,
    analysis_completed_date,
    source_completed_this_cycle: bool,
) -> bool:
    """Run one same-day analysis after all real source inputs have completed.

    The explicit source-completion trigger lets a later successful AQI retry
    finish an analytical snapshot when the satellite composites succeeded
    earlier that day. It never treats prior-day data as current or forward-fills
    a missing source.
    """
    return (
        source_completed_this_cycle
        and satellite_ready_date == today
        and aqi_ready_date == today
        and analysis_completed_date != today
    )


def run_scheduler() -> None:
    last_run: dict[str, datetime | None] = {"aqi": None, "s2": None, "lst": None}
    satellite_ready_date = None
    aqi_ready_date = None
    analysis_completed_date = None
    logger.info("GeoSense scheduler started: %s", describe_schedule())
    while True:
        now = datetime.now(timezone.utc)
        today = now.date()
        ran_aqi = False
        if last_run["aqi"] is None or now - last_run["aqi"] >= AQI_INTERVAL:
            try:
                logger.info("Running AQI/IDW cycle")
                logger.info("AQI/IDW report: %s", run_aqi_cycle())
                ran_aqi = True
                aqi_ready_date = today
            except Exception:
                logger.exception("AQI/IDW cycle failed")
            finally:
                last_run["aqi"] = now

        ran_s2 = False
        if last_run["s2"] is None or now - last_run["s2"] >= S2_INTERVAL:
            try:
                logger.info("Running Sentinel-2 cycle")
                logger.info("Sentinel-2 report: %s", _run_s2_for_today(today))
                ran_s2 = True
            except Exception:
                logger.exception("Sentinel-2 cycle failed")
            finally:
                last_run["s2"] = now

        ran_lst = False
        if last_run["lst"] is None or now - last_run["lst"] >= LST_INTERVAL:
            try:
                logger.info("Running Landsat cycle")
                logger.info("Landsat report: %s", _run_lst_for_today(today))
                ran_lst = True
            except Exception:
                logger.exception("Landsat cycle failed")
            finally:
                last_run["lst"] = now

        if ran_s2 and ran_lst:
            satellite_ready_date = today

        # No forward fill: only attempt a model snapshot after both satellite
        # sources and AQI completed for the same UTC date. If AQI initially
        # fails, its next successful scheduled run can complete this day's
        # pending snapshot without waiting for another satellite cadence.
        if should_run_feature_pipeline(
            today=today,
            satellite_ready_date=satellite_ready_date,
            aqi_ready_date=aqi_ready_date,
            analysis_completed_date=analysis_completed_date,
            source_completed_this_cycle=ran_aqi or (ran_s2 and ran_lst),
        ):
            try:
                logger.info("Running Phase 2 snapshot for %s", today.isoformat())
                logger.info("Feature/anomaly report: %s", run_feature_anomaly_pipeline(today))
                analysis_completed_date = today
            except ValueError as exc:
                logger.warning("No valid same-day analytical snapshot: %s", exc)
            except Exception:
                logger.exception("Feature/anomaly cycle failed")

        time.sleep(POLL_SECONDS)


def run_aqi_scheduler() -> None:
    """Run only the existing OpenAQ/CPCB/IDW cycle at its configured cadence."""
    last_run: datetime | None = None
    logger.info("AQI-only scheduler started; cadence=%s", AQI_INTERVAL)
    while True:
        now = datetime.now(timezone.utc)
        if last_run is None or now - last_run >= AQI_INTERVAL:
            try:
                logger.info("Running AQI/IDW cycle")
                logger.info("AQI/IDW report: %s", run_aqi_cycle())
            except Exception:
                logger.exception("AQI/IDW cycle failed; no fallback values were generated")
            finally:
                last_run = now
        time.sleep(POLL_SECONDS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the current GeoSense ingestion scheduler")
    parser.add_argument("--dry-run", action="store_true", help="Print cadence and exit without reading or writing data")
    parser.add_argument("--aqi-only", action="store_true", help="Run only the existing OpenAQ/CPCB/IDW scheduler cycle")
    args = parser.parse_args()
    if args.dry_run:
        if args.aqi_only:
            print(f"aqi_idw: every {AQI_INTERVAL}; CPCB/MPCB-backed OpenAQ stations only")
        else:
            for name, detail in describe_schedule().items():
                print(f"{name}: {detail}")
        return 0
    if args.aqi_only:
        run_aqi_scheduler()
        return 0
    run_scheduler()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
