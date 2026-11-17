"""Read-only pipeline status of the current city (SELECT queries and file reads only)."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from app.core.cities import city_path, get_city

MANIFEST = city_path("surfaces", "manifest.json")
LAYERS = ("ndvi", "lst", "water_health", "aqi", "composite", "ndmi")


def _layers() -> dict[str, Any]:
    try:
        s = json.loads(MANIFEST.read_text(encoding="utf-8")).get("surfaces") or {}
    except Exception:
        return {k: {"status": "not_generated"} for k in LAYERS}
    out = {}
    for k in LAYERS:
        r = s.get(k) or {}
        out[k] = {"status": r.get("generation_status") or ("generated" if r else "not_generated"),
                  "generated_at": r.get("generated_at"),
                  "period": r.get("source_period") or None}
    return out


def get_operational_status(db) -> dict[str, Any]:
    city = get_city()
    p = {"city": city.id}
    cells = db.execute(text("SELECT count(*) FROM spatial_cells WHERE city = :city"), p).scalar() or 0
    snap = db.execute(text("""
        SELECT max(ef.observed_at) AS latest, count(DISTINCT ef.observed_at) AS snapshots
        FROM engineered_features ef JOIN spatial_cells sc ON sc.id = ef.cell_id WHERE sc.city = :city
    """), p).mappings().one()
    models = db.execute(text("""
        WITH latest AS (
            SELECT ar.model_name, max(ar.observed_at) AS obs
            FROM anomaly_results ar JOIN spatial_cells sc ON sc.id = ar.cell_id
            WHERE sc.city = :city GROUP BY ar.model_name
        )
        SELECT ar.model_name, latest.obs, count(*) AS scored, count(*) FILTER (WHERE ar.is_anomaly) AS flagged
        FROM anomaly_results ar JOIN latest ON latest.model_name = ar.model_name AND latest.obs = ar.observed_at
        JOIN spatial_cells sc ON sc.id = ar.cell_id
        WHERE sc.city = :city
        GROUP BY ar.model_name, latest.obs ORDER BY ar.model_name
    """), p).mappings().all()
    seasons = db.execute(text("SELECT count(*) FROM history_seasons WHERE city = :city"), p).scalar() or 0
    return {
        "city": city.id,
        "cells": int(cells),
        "ml_snapshot": {"latest": snap["latest"].isoformat() if snap["latest"] else None,
                        "snapshots": int(snap["snapshots"] or 0)},
        "models": [{"model": r["model_name"], "observed_at": r["obs"].isoformat() if r["obs"] else None,
                    "cells_scored": int(r["scored"]), "cells_flagged": int(r["flagged"])} for r in models],
        "layers": _layers(),
        "history_seasons": int(seasons),
        "xgboost": _xgboost_status(),
        "aqi_auto_refresh": _aqi_refresh_status(),
    }


def _xgboost_status() -> dict[str, Any]:
    """The 300 m cell heat model (LST from land cover), from the ML pipeline's summary."""
    try:
        from app.services.rag.explainer import ml_summary
        x = (ml_summary() or {}).get("xgboost_lst") or {}
        m = x.get("metrics") or {}
        return {"target": "cell mean LST (Landsat)", "trained": x.get("status") == "ok",
                "r2_spatial_cv": m.get("r2_spatial_cv"), "rmse_c": m.get("rmse_c"), "cv": m.get("cv")}
    except Exception as exc:
        return {"trained": False, "reason": str(exc)}


def _aqi_refresh_status() -> dict[str, Any]:
    from app.services.surfaces import aqi_refresh
    st = aqi_refresh.state()
    return {"enabled": aqi_refresh.enabled(), "layer_age_hours": aqi_refresh.layer_age_hours(),
            "running": st["running"], "last_attempt": st["last_attempt"], "last_result": st["last_result"]}
