"""Orchestrates cell features -> models -> persisted results."""
from __future__ import annotations

from typing import Any

from app.services.ml.cell_features import (
    compute_cell_features, export_csv, load_cells, persist_cell_features, snapshot_timestamp,
)
import json

from app.services.ml.cell_models import (
    persist_results, run_isolation_forest, run_layer_isolation_forests, run_station_isolation_forest,
    run_water_health, run_xgboost_lst, write_summary,
)


def _aqi_stations() -> list[dict]:
    from pathlib import Path
    p = Path(__file__).resolve().parents[3] / "data" / "surfaces" / "manifest.json"
    try:
        aqi = json.loads(p.read_text(encoding="utf-8"))["surfaces"].get("aqi") or {}
    except Exception:
        return []
    return aqi.get("stations") or [] if aqi.get("available") else []


def _aqi_record() -> dict:
    from pathlib import Path
    p = Path(__file__).resolve().parents[3] / "data" / "surfaces" / "manifest.json"
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))["surfaces"].get("aqi") or {}
    except Exception:
        return {}
    return rec if rec.get("available") else {}


def run_cell_ml_pipeline(db) -> dict[str, Any]:
    cells = load_cells(db)
    if not cells:
        raise RuntimeError("spatial_cells is empty — run scripts/generate_spatial_cells.py first")
    rows, sources = compute_cell_features(cells)
    observed_at = snapshot_timestamp(sources)
    persist_cell_features(db, rows, sources, observed_at)
    csv_path = export_csv(rows, observed_at)

    iso = run_isolation_forest(rows)
    xgbr = run_xgboost_lst(rows)
    wh = run_water_health(rows)
    layers = run_layer_isolation_forests(rows)
    stations = run_station_isolation_forest(_aqi_stations())
    written = persist_results(db, observed_at, iso, xgbr, wh, layers)
    db.commit()
    from app.services.ml.relationships import compute_relationships
    st_list = _aqi_stations()
    rel = compute_relationships(rows, n_stations=len(st_list) or None)
    from app.services.ml.validation import compute_validation
    val = compute_validation(rows, xgbr.get("results"), layers.get("lst"), _aqi_record())
    summary_path = write_summary(observed_at, sources, iso, xgbr, wh, len(cells), rows, layers, stations,
                                 extras={"relationships": rel, "validation": val})
    return {
        "snapshot_at": observed_at.isoformat(),
        "cells": len(cells),
        "feature_csv": csv_path.name,
        "isolation_forest": {k: iso.get(k) for k in ("status", "eligible", "excluded", "anomalies", "features")},
        "xgboost_lst": {k: xgbr.get(k) for k in ("status", "metrics", "flags", "feature_importance_gain")},
        "water_health": {k: wh.get(k) for k in ("status", "eligible", "median", "flags")},
        "layer_isolation_forest": {k: {kk: v.get(kk) for kk in ("status", "eligible", "anomalies", "unusually_high",
                                                                "unusually_low", "unusual_pattern")}
                                   for k, v in layers.items()},
        "station_isolation_forest": {k: stations.get(k) for k in ("status", "eligible", "anomalies", "pollutants")},
        "relationships": [f"{p['label']}: rho {p['all']['spearman_rho']:+.2f} ({p['all']['strength']})"
                          for p in rel["pairs"]],
        "validation": {"worldcover": val["worldcover"].get("status"),
                       "dominant_class_agreement_pct": val["worldcover"].get("dominant_class_agreement_pct"),
                       "aqi_loso_mae": val["aqi_idw_loso"].get("mae")},
        "anomaly_rows_written": written,
        "summary_file": summary_path.name,
    }
