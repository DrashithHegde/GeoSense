"""Idempotent, observable entrypoint for GeoSense Azure Container Apps Jobs."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT))

_RASTERIO_PROJ_DATA = Path(sys.prefix) / "Lib" / "site-packages" / "rasterio" / "proj_data"
if _RASTERIO_PROJ_DATA.is_dir():
    os.environ["PROJ_LIB"] = str(_RASTERIO_PROJ_DATA)
    os.environ["PROJ_DATA"] = str(_RASTERIO_PROJ_DATA)

from app.core.cities import get_city, use_city  # noqa: E402
from app.services.ingestion_log import finish_run, start_run  # noqa: E402


def _bootstrap_gee_credentials() -> None:
    """Write GEE_SERVICE_ACCOUNT_JSON (if set) to a private temp file for GOOGLE_APPLICATION_CREDENTIALS."""
    sa_json = os.getenv("GEE_SERVICE_ACCOUNT_JSON", "").strip()
    if sa_json and not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        target = Path(tempfile.gettempdir()) / "gee-sa.json"
        target.write_text(sa_json, encoding="utf-8")
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(target)


def _manifest_record(city: str, layer: str) -> dict[str, Any]:
    path = get_city(city).data_dir / "surfaces" / "manifest.json"
    if not path.exists():
        return {}
    try:
        return (json.loads(path.read_text(encoding="utf-8")).get("surfaces") or {}).get(layer) or {}
    except Exception:
        return {}


def _parse_iso(val: str | None) -> datetime | None:
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _check_new_satellite_imagery(city: str, task: str) -> tuple[bool, datetime | None, str]:
    """Return (has_new_imagery, latest_scene_ts, reason) without inventing observations."""
    _bootstrap_gee_credentials()
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS") and not (Path.home() / ".config" / "earthengine" / "credentials").exists():
        raise RuntimeError("GEE credentials not configured (set GEE_SERVICE_ACCOUNT_JSON or GOOGLE_APPLICATION_CREDENTIALS)")

    import ee
    from app.services.municipality_boundaries import get_study_region_bounds
    from gee.gee_client import initialize_ee

    initialize_ee()
    with use_city(city):
        bounds = get_study_region_bounds()
        region = ee.Geometry.Rectangle(list(bounds), proj="EPSG:4326", geodesic=False)
        now = datetime.now(timezone.utc)
        if task in ("ndvi", "water", "indices"):
            col_id = "COPERNICUS/S2_SR_HARMONIZED"
            window_days = 14
            manifest_key = "water_health" if task == "water" else task
            col = ee.ImageCollection(col_id).filterBounds(region).filterDate((now - timedelta(days=window_days)).strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d"))
        else:
            window_days = 45
            manifest_key = "lst"
            l8 = ee.ImageCollection("LANDSAT/LC08/C02/T1_L2").filterBounds(region)
            l9 = ee.ImageCollection("LANDSAT/LC09/C02/T1_L2").filterBounds(region)
            col = l8.merge(l9).filterDate((now - timedelta(days=window_days)).strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d"))

        size = int(col.size().getInfo())
        if size == 0:
            return False, None, f"0 scenes in last {window_days}d"
        latest_ms = col.aggregate_max("system:time_start").getInfo()
        if not latest_ms:
            return False, None, "no system:time_start metadata"
        latest_dt = datetime.fromtimestamp(float(latest_ms) / 1000.0, tz=timezone.utc)

        prev_rec = _manifest_record(city, manifest_key)
        prev_ts = _parse_iso(prev_rec.get("source_timestamp"))
        if prev_ts and latest_dt <= prev_ts:
            return False, latest_dt, f"latest scene {latest_dt.isoformat()} <= existing {prev_ts.isoformat()}"
        return True, latest_dt, f"new scene {latest_dt.isoformat()} ({size} scenes in {window_days}d)"


def _run_cmd(command: list[str], timeout_s: int = 1800) -> int:
    print("$ " + " ".join(command), flush=True)
    proc = subprocess.run(command, cwd=SERVER_ROOT, timeout=timeout_s)
    return proc.returncode


def _run_fast_ml(city: str) -> dict[str, Any]:
    """Run cell ML pipeline with psycopg2 execute_values batching."""
    from psycopg2.extras import execute_values
    from app.database import get_db
    from app.services.ml import cell_features as cf
    from app.services.ml import cell_models as cm
    from app.services.ml import pipeline as ml_pipeline

    orig_feat = ml_pipeline.persist_cell_features
    orig_res = ml_pipeline.persist_results

    def fast_feats(db, rows, sources, observed_at):
        meta = json.dumps({"cell_features": {"version": cf.FEATURE_VERSION, "sources": sources, "computed_at": datetime.now(timezone.utc).isoformat()}})
        env_rows = [
            (
                r["cell_id"], observed_at, r.get("ndvi_mean"), r.get("lst_mean"), r.get("wh_mean"),
                None if r.get("water_px") is None else r["water_px"] * 100.0,
                None if r.get("aqi_idw") is None else int(round(r["aqi_idw"])),
                "openaq_cpcb_idw" if r.get("aqi_idw") is not None else None, meta,
            )
            for r in rows
        ]
        raw = db.connection().connection
        with raw.cursor() as cur:
            execute_values(
                cur,
                """
                INSERT INTO environment_data (cell_id, observed_at, ndvi, lst, water_health_score, water_extent_m2,
                                              aqi, aqi_source_type, source_metadata)
                VALUES %s
                ON CONFLICT (cell_id, observed_at) DO UPDATE SET
                    ndvi = EXCLUDED.ndvi, lst = EXCLUDED.lst, water_health_score = EXCLUDED.water_health_score,
                    water_extent_m2 = EXCLUDED.water_extent_m2, aqi = EXCLUDED.aqi,
                    aqi_source_type = EXCLUDED.aqi_source_type,
                    source_metadata = environment_data.source_metadata || EXCLUDED.source_metadata
                """,
                env_rows,
                template="(%s, %s, %s, %s, %s, %s, %s, %s, CAST(%s AS jsonb))",
                page_size=1000,
            )
            cur.execute("SELECT cell_id, id FROM environment_data WHERE observed_at = %s", (observed_at,))
            env_map = {cid: eid for cid, eid in cur.fetchall()}
            feat_rows = [
                (
                    r["cell_id"], observed_at,
                    json.dumps({"schema_version": "2.0", "feature_version": cf.FEATURE_VERSION, "raw_values": r,
                                "sources": sources, "snapshot_at": observed_at.isoformat()}),
                    env_map[r["cell_id"]],
                )
                for r in rows
            ]
            execute_values(
                cur,
                """
                INSERT INTO engineered_features (cell_id, observed_at, feature_values, environment_data_id)
                VALUES %s
                ON CONFLICT (cell_id, observed_at) DO UPDATE SET
                    feature_values = EXCLUDED.feature_values, environment_data_id = EXCLUDED.environment_data_id
                """,
                feat_rows,
                template="(%s, %s, CAST(%s AS jsonb), %s)",
                page_size=1000,
            )
        return len(env_rows)

    def fast_res(db, observed_at, iso, xgbr, wh, layers=None):
        now = datetime.now(timezone.utc)
        payload = []
        for layer, lr in (layers or {}).items():
            for cid, r in lr.get("results", {}).items():
                top = ", ".join(f"{d['label']} {d['direction']} norm ({d['z']:+.1f}σ)" for d in r["dominant_deviations"][:2])
                word = {"high": "unusually high", "low": "unusually low", "pattern": "unusual pattern"}[r["direction"]]
                payload.append((cid, observed_at, now, r["score"], r["is_anomaly"], lr["model"],
                                f"{layer}_{r['direction']}_outlier" if r["is_anomaly"] else f"{layer}_inlier",
                                f"{lr['name']}: {word} ({top})." if r["is_anomaly"] else None,
                                json.dumps({"model": lr["model"], "features": lr["features"], **r}, default=float)))
        for cid, r in iso.get("results", {}).items():
            top = ", ".join(f"{d['label']} {d['direction']} city norm ({d['z']:+.1f}σ)" for d in r["dominant_deviations"][:2])
            payload.append((cid, observed_at, now, r["score"], r["is_anomaly"], cm.IF_MODEL,
                            "isolation_forest_spatial_anomaly" if r["is_anomaly"] else "isolation_forest_spatial_inlier",
                            f"Multivariate outlier: {top}." if r["is_anomaly"] else None,
                            json.dumps({"model": cm.IF_MODEL, "features": iso["features"], **r}, default=float)))
        for cid, r in xgbr.get("results", {}).items():
            payload.append((cid, observed_at, now, r["residual_c"], r["flag"] != "explained", cm.XGB_MODEL, r["flag"],
                            (f"Observed LST {r['observed_lst_c']}°C vs {r['expected_lst_c']}°C expected from land cover "
                             f"(residual {r['residual_c']:+.1f}°C).") if r["flag"] != "explained" else None,
                            json.dumps({"model": cm.XGB_MODEL, "cv_metrics": xgbr["metrics"], **r}, default=float)))
        for cid, r in wh.get("results", {}).items():
            payload.append((cid, observed_at, now, r["robust_z"], r["flag"] == "low_water_condition", cm.WH_MODEL, r["flag"],
                            (f"Water Health index {r['wh_mean']:.3f} is {abs(r['robust_z']):.1f} robust-σ below the "
                             f"median of water cells.") if r["flag"] == "low_water_condition" else None,
                            json.dumps({"model": cm.WH_MODEL, "median": wh["median"], "mad_scaled": wh["mad_scaled"], **r}, default=float)))
        names = [cm.IF_MODEL, cm.XGB_MODEL, cm.WH_MODEL] + [c["model"] for c in cm.LAYER_IF.values()]
        raw = db.connection().connection
        with raw.cursor() as cur:
            cur.execute("DELETE FROM anomaly_results WHERE observed_at = %s AND model_name = ANY(%s) "
                        "AND cell_id IN (SELECT id FROM spatial_cells WHERE city = %s)", (observed_at, names, city))
            if payload:
                cur.execute("SELECT cell_id, id FROM environment_data WHERE observed_at = %s", (observed_at,))
                env_map = {cid: eid for cid, eid in cur.fetchall()}
                cur.execute("SELECT cell_id, id FROM engineered_features WHERE observed_at = %s", (observed_at,))
                feat_map = {cid: fid for cid, fid in cur.fetchall()}
                rows_db = [(*row, feat_map.get(row[0]), env_map.get(row[0])) for row in payload]
                execute_values(
                    cur,
                    """
                    INSERT INTO anomaly_results (cell_id, observed_at, detected_at, anomaly_score, is_anomaly, model_name,
                                                 anomaly_type, root_cause, evidence, engineered_feature_id, environment_data_id)
                    VALUES %s
                    ON CONFLICT (cell_id, observed_at, model_name) DO UPDATE SET
                        detected_at = EXCLUDED.detected_at, anomaly_score = EXCLUDED.anomaly_score,
                        is_anomaly = EXCLUDED.is_anomaly, anomaly_type = EXCLUDED.anomaly_type,
                        root_cause = EXCLUDED.root_cause, evidence = EXCLUDED.evidence
                    """,
                    rows_db,
                    template="(%s, %s, %s, %s, %s, %s, %s, %s, CAST(%s AS jsonb), %s, %s)",
                    page_size=1000,
                )
        return len(payload)

    ml_pipeline.persist_cell_features = fast_feats
    ml_pipeline.persist_results = fast_res
    try:
        with use_city(city), get_db() as db:
            return ml_pipeline.run_cell_ml_pipeline(db)
    finally:
        ml_pipeline.persist_cell_features = orig_feat
        ml_pipeline.persist_results = orig_res


def _trigger_backend_reload() -> None:
    import requests
    url = os.getenv("BACKEND_RELOAD_URL", "").strip()
    token = os.getenv("ADMIN_TOKEN", "").strip()
    if not url:
        return
    headers = {"X-Admin-Token": token} if token else {}
    for attempt in range(1, 4):
        try:
            r = requests.post(url, headers=headers, timeout=180)
            r.raise_for_status()
            print(f"Backend reload succeeded: {r.text[:200]}", flush=True)
            return
        except Exception as exc:
            print(f"Backend reload attempt {attempt} failed: {exc}", flush=True)
            if attempt < 3:
                time.sleep(3 * attempt)
    raise RuntimeError("Backend reload failed after 3 attempts")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a GeoSense Azure Container Apps Job")
    parser.add_argument("--job-name", default=os.getenv("CONTAINER_APP_JOB_NAME", "manual-job"))
    parser.add_argument("--city", choices=["mumbai", "delhi", "bengaluru"], default="mumbai")
    parser.add_argument(
        "--only",
        choices=["migrate", "aqi", "composite", "ndvi", "lst", "water", "indices", "render", "ml", "prune", "bundle", "reload"],
        action="append",
    )
    parser.add_argument("--publish", action="store_true", help="Pack, validate, upload to Blob, and reload backend if data updated")
    parser.add_argument("--force", action="store_true", help="Skip new-imagery check and force extraction")
    args = parser.parse_args()

    _bootstrap_gee_credentials()
    import scripts.data_bundle as db_mod

    # Ensure job starts from the latest durable bundle in Blob Storage
    urls = [u.strip() for u in os.getenv("DATA_BUNDLE_URL", "").split(",") if u.strip()]
    if os.getenv("AZURE_STORAGE_ACCOUNT_URL") or urls:
        db_mod.fetch(urls, force=True)

    only = args.only or ["aqi", "composite"]
    updated_any = False

    for task in only:
        run_id = start_run(args.job_name, args.city, task)
        try:
            if task == "migrate":
                rc = _run_cmd([sys.executable, "scripts/db_init.py"], timeout_s=300)
                if rc != 0:
                    raise RuntimeError(f"db_init exited {rc}")
                finish_run(run_id, status="succeeded")
                continue

            if task == "bundle":
                rc = _run_cmd([sys.executable, "scripts/upload_data_bundle.py"], timeout_s=600)
                if rc != 0:
                    raise RuntimeError(f"upload_data_bundle exited {rc}")
                finish_run(run_id, status="succeeded")
                continue

            if task == "reload":
                _trigger_backend_reload()
                finish_run(run_id, status="succeeded")
                continue

            if task in ("ndvi", "water", "lst", "indices") and not args.force:
                has_new, latest_dt, reason = _check_new_satellite_imagery(args.city, task)
                print(f"[{task}] imagery check: {reason}", flush=True)
                if not has_new:
                    finish_run(run_id, status="skipped_no_new_data", source_timestamp=latest_dt, metadata={"reason": reason})
                    continue

            if task == "ml":
                summary = _run_fast_ml(args.city)
                snap_ts = _parse_iso(summary.get("snapshot_at"))
                finish_run(
                    run_id,
                    status="succeeded",
                    source_timestamp=snap_ts,
                    records_processed=int(summary.get("anomaly_rows_written") or 0),
                    metadata={"cells": summary.get("cells")},
                )
                updated_any = True
                continue

            script_map = {
                "aqi": "scripts/generate_aqi_station_surface.py",
                "composite": "scripts/generate_composite_surface.py",
                "ndvi": "scripts/generate_ndvi_surface.py",
                "water": "scripts/generate_water_health_surface.py",
                "lst": "scripts/generate_lst_surface.py",
                "indices": "scripts/generate_index_surfaces.py",
                "render": "scripts/render_heatmaps.py",
                "prune": "scripts/prune_surfaces.py",
            }
            cmd = [sys.executable, script_map[task], "--city", args.city]
            if task == "render":
                cmd += ["--only", "ndvi", "--only", "water_health", "--only", "lst"]
            rc = _run_cmd(cmd, timeout_s=1800)
            if rc != 0:
                raise RuntimeError(f"{script_map[task]} exited {rc}")

            mkey = "water_health" if task == "water" else task
            rec = _manifest_record(args.city, mkey)
            src_ts = _parse_iso(rec.get("source_timestamp") or rec.get("generated_at"))
            recs = len(rec.get("stations") or []) if task == "aqi" else rec.get("valid_pixels")
            finish_run(
                run_id,
                status="succeeded",
                source_timestamp=src_ts,
                records_processed=int(recs) if isinstance(recs, (int, float)) else None,
                metadata={"generation_status": rec.get("generation_status")},
            )
            if task != "prune":
                updated_any = True
        except Exception as exc:
            finish_run(run_id, status="failed", error_message=str(exc))
            print(f"[{task}] FAILED: {exc}", file=sys.stderr, flush=True)
            return 1

    if args.publish and updated_any:
        pub_run_id = start_run(args.job_name, args.city, "publish")
        try:
            archive = Path(tempfile.gettempdir()) / "geosense-data.tar.gz"
            cities = [args.city] if os.getenv("PUBLISH_SINGLE_CITY") else None
            if not cities:
                from app.core.cities import CITIES
                cities = [c for c in CITIES if (CITIES[c].data_dir / "surfaces" / "manifest.json").exists()]
            db_mod.pack(archive, cities)
            pointer = db_mod.publish_to_blob(archive)
            _trigger_backend_reload()
            finish_run(
                pub_run_id,
                status="succeeded",
                bundle_blob=pointer.get("blob"),
                metadata={"sha256": pointer.get("sha256"), "size_bytes": pointer.get("size_bytes")},
            )
        except Exception as exc:
            finish_run(pub_run_id, status="failed", error_message=str(exc))
            print(f"[publish] FAILED: {exc}", file=sys.stderr, flush=True)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
