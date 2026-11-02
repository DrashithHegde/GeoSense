"""Cell-level ML for GeoSense (300 m analytical grid).

Three complementary, evidence-producing models — all trained on real satellite
features from `cell_features`:

1. Isolation Forest (multivariate spatial outliers)
     features: NDVI mean/std, vegetation/built/open-water fractions, LST mean/std
               (+ CPCB AQI when a real station surface exists for >=90% cells)
     output:   anomaly score, flag, per-feature z-scores, dominant deviations

2. XGBoost LST model ("does land cover explain this heat?")
     y = cell mean LST (Landsat), X = land-cover features from Sentinel-2
     spatial block cross-validation (3 km blocks) -> honest R²/RMSE
     out-of-fold residual = observed - expected  -> unexplained heat / coolness
     TreeSHAP contributions (xgboost pred_contribs) -> per-cell drivers in °C

3. Water Health robust z-score (median/MAD among water cells)
     flags water bodies whose satellite condition index is unusually low.

4. Per-layer Isolation Forests (one per map layer: NDVI, LST, Water Health, AQI)
     features: the cell's value, its within-cell variability, and its contrast with
               the surrounding ~1 km (cell value minus neighbour mean)
     output:   "unusually high / low / patchy for this layer" with z-scores

5. Station Isolation Forest (OpenAQ CPCB/MPCB stations)
     features: CPCB pollutant sub-indices (PM2.5, PM10, NO2, SO2, O3, CO)
     output:   stations whose pollutant mix is unusual relative to other stations

Everything is a statistical signal, not proof of cause.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn import __version__ as sklearn_version
from sklearn.ensemble import IsolationForest
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler
from sqlalchemy import text

from app.services.ml.cell_features import ML_DIR

IF_MODEL = "isolation_forest_cell_v2"
XGB_MODEL = "xgboost_lst_residual_v1"
WH_MODEL = "water_health_robust_z_v1"

IF_MAX_WATER_FRAC = 0.5
# Land-normalised features: shares are of the cell's LAND area, so shoreline cells
# are not flagged merely for containing some water.
IF_BASE_FEATURES = ["ndvi_land_mean", "ndvi_std", "veg_land_frac", "built_land_frac", "lst_mean", "lst_std"]
XGB_FEATURES = ["ndvi_mean", "ndvi_std", "veg_frac", "built_frac", "openwater_frac", "water_frac", "dist_water_m"]
LABELS = {
    "ndvi_mean": "NDVI (mean)", "ndvi_std": "NDVI variability", "veg_frac": "dense-vegetation share",
    "built_frac": "built/bare share", "openwater_frac": "open-water share", "water_frac": "detected water share",
    "lst_mean": "LST (mean)", "dist_water_m": "distance to open water", "lst_std": "LST variability", "aqi_idw": "CPCB AQI (IDW)",
    "ndvi_land_mean": "NDVI of land (mean)", "veg_land_frac": "dense-vegetation share of land",
    "built_land_frac": "built/bare share of land",
}
LABELS.update({
    "ndvi_local_diff": "NDVI vs surrounding 1 km", "lst_local_diff": "LST vs surrounding 1 km",
    "wh_mean": "Water Health index", "wh_std": "Water Health variability",
    "wh_local_diff": "Water Health vs nearby water", "aqi_local_diff": "AQI vs surrounding 1 km",
})
IF_CONTAMINATION = 0.05
LOCAL_RADIUS_M = 1000.0

# One Isolation Forest per map layer. "value" is the layer's main feature (used for
# the high/low direction); "land_only" keeps water cells out of the NDVI model.
LAYER_IF = {
    "ndvi": {"model": "isolation_forest_ndvi_v1", "value": "ndvi_land_mean",
             "features": ["ndvi_land_mean", "ndvi_std", "ndvi_local_diff"], "land_only": True,
             "name": "NDVI (vegetation)"},
    "lst": {"model": "isolation_forest_lst_v1", "value": "lst_mean",
            "features": ["lst_mean", "lst_std", "lst_local_diff"], "land_only": False,
            "name": "LST (surface temperature)"},
    "water_health": {"model": "isolation_forest_water_health_v1", "value": "wh_mean",
                     "features": ["wh_mean", "wh_std", "wh_local_diff"], "land_only": False,
                     "name": "Water Health"},
    # AQI between stations is an IDW estimate from the k nearest stations; that surface
    # steps wherever the nearest-station set changes, so a "contrast with neighbours"
    # feature would flag interpolation seams, not pollution. The AQI layer model therefore
    # uses the interpolated value only; pollutant-mix anomalies come from the station model.
    "aqi": {"model": "isolation_forest_aqi_v1", "value": "aqi_idw",
            "features": ["aqi_idw"], "land_only": False,
            "name": "CPCB AQI (interpolated)"},
}
STATION_IF_MODEL = "isolation_forest_aqi_station_v1"
POLLUTANTS = ("pm25", "pm10", "no2", "so2", "o3", "co")
POLLUTANT_LABELS = {"pm25": "PM2.5", "pm10": "PM10", "no2": "NO₂", "so2": "SO₂", "o3": "O₃", "co": "CO"}
RANDOM_STATE = 42
BLOCK_DEG = 0.027  # ~3 km spatial CV blocks


def _matrix(rows, feats):
    X = np.array([[r.get(f) if r.get(f) is not None else np.nan for f in feats] for r in rows], dtype="float64")
    return X


def _add_land_shares(rows: list[dict]) -> None:
    for r in rows:
        ow = r.get("openwater_frac")
        land = None if ow is None else 1.0 - float(ow)
        for src, dst in (("veg_frac", "veg_land_frac"), ("built_frac", "built_land_frac")):
            v = r.get(src)
            r[dst] = (float(v) / land) if (v is not None and land and land > 0.05) else None


def run_isolation_forest(rows: list[dict]) -> dict[str, Any]:
    _add_land_shares(rows)
    feats = list(IF_BASE_FEATURES)
    aqi_cov = np.mean([r.get("aqi_idw") is not None for r in rows]) if rows else 0
    if aqi_cov >= 0.9:
        feats.append("aqi_idw")
    X = _matrix(rows, feats)
    # Land cells only: water-dominated cells are rare, so an unsupervised detector
    # would mostly flag "this is water". Water cells are assessed by the Water
    # Health robust-z model instead.
    ow = np.array([r.get("openwater_frac") if r.get("openwater_frac") is not None else np.nan for r in rows], float)
    land = ~(ow > IF_MAX_WATER_FRAC)
    ok = np.all(np.isfinite(X), axis=1) & land
    if ok.sum() < 50:
        return {"status": "insufficient", "eligible": int(ok.sum()), "features": feats, "results": {}}
    scaler = StandardScaler().fit(X[ok])
    Z = scaler.transform(X[ok])
    model = IsolationForest(n_estimators=300, contamination=IF_CONTAMINATION, random_state=RANDOM_STATE)
    pred = model.fit_predict(Z)
    score = -model.score_samples(Z)
    eligible_rows = [r for r, k in zip(rows, ok) if k]
    results = {}
    for i, r in enumerate(eligible_rows):
        z = {f: float(Z[i, j]) for j, f in enumerate(feats)}
        dom = sorted(feats, key=lambda f: abs(z[f]), reverse=True)[:3]
        results[r["cell_id"]] = {
            "is_anomaly": bool(pred[i] == -1),
            "score": float(score[i]),
            "score_percentile": float((score < score[i]).mean() * 100),
            "z_scores": z,
            "dominant_deviations": [{"feature": f, "label": LABELS[f], "z": round(z[f], 2),
                                     "direction": "above" if z[f] > 0 else "below", "value": r.get(f)} for f in dom],
        }
    ML_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "scaler": scaler, "features": feats}, ML_DIR / f"{IF_MODEL}.joblib")
    return {"status": "ok", "eligible": int(ok.sum()), "excluded": int((~ok).sum()), "features": feats,
            "excluded_water_cells": int((~land).sum()),
            "anomalies": int((pred == -1).sum()), "contamination": IF_CONTAMINATION, "results": results,
            "excluded_reason": f"water-dominated (> {int(IF_MAX_WATER_FRAC*100)}% open water; assessed by the Water "
                               "Health model), missing LST (cloud) or NDVI coverage < 30% of cell"}


def _add_local_contrast(rows: list[dict], radius_m: float = LOCAL_RADIUS_M) -> None:
    """value minus the mean of other cells within radius_m (no fill: needs >=3 neighbours with data)."""
    from scipy.spatial import cKDTree
    lat0 = np.nanmean([r["lat"] for r in rows])
    xy = np.array([[r["lon"] * 111320.0 * np.cos(np.radians(lat0)), r["lat"] * 110540.0] for r in rows])
    tree = cKDTree(xy)
    neigh = tree.query_ball_point(xy, r=radius_m)
    for src, dst in (("ndvi_land_mean", "ndvi_local_diff"), ("lst_mean", "lst_local_diff"),
                     ("wh_mean", "wh_local_diff"), ("aqi_idw", "aqi_local_diff")):
        vals = np.array([r.get(src) if r.get(src) is not None else np.nan for r in rows], float)
        for i, idx in enumerate(neigh):
            if not np.isfinite(vals[i]):
                rows[i][dst] = None
                continue
            nb = vals[[j for j in idx if j != i]]
            nb = nb[np.isfinite(nb)]
            rows[i][dst] = float(vals[i] - nb.mean()) if nb.size >= 3 else None


def _fit_if(X: np.ndarray, contamination: float):
    scaler = StandardScaler().fit(X)
    Z = scaler.transform(X)
    model = IsolationForest(n_estimators=300, contamination=contamination, random_state=RANDOM_STATE)
    pred = model.fit_predict(Z)
    score = -model.score_samples(Z)
    return model, scaler, Z, pred, score


def run_layer_isolation_forests(rows: list[dict]) -> dict[str, Any]:
    """One Isolation Forest per map layer, so every layer has its own anomaly view."""
    _add_land_shares(rows)
    _add_local_contrast(rows)
    ow = np.array([r.get("openwater_frac") if r.get("openwater_frac") is not None else np.nan for r in rows], float)
    land = ~(ow > IF_MAX_WATER_FRAC)
    out: dict[str, Any] = {}
    for layer, cfg in LAYER_IF.items():
        feats = cfg["features"]
        X = _matrix(rows, feats)
        ok = np.all(np.isfinite(X), axis=1) & (land if cfg["land_only"] else True)
        if ok.sum() < 100:
            out[layer] = {"status": "insufficient", "eligible": int(ok.sum()), "model": cfg["model"],
                          "name": cfg["name"], "features": feats, "results": {}}
            continue
        model, scaler, Z, pred, score = _fit_if(X[ok], IF_CONTAMINATION)
        vi = feats.index(cfg["value"])
        results, high, low, patchy = {}, 0, 0, 0
        for i, r in enumerate([r for r, k in zip(rows, ok) if k]):
            z = {f: float(Z[i, j]) for j, f in enumerate(feats)}
            zv = z[cfg["value"]]
            direction = "high" if zv >= 1.0 else "low" if zv <= -1.0 else "pattern"
            anom = bool(pred[i] == -1)
            if anom:
                high += direction == "high"; low += direction == "low"; patchy += direction == "pattern"
            dom = sorted(feats, key=lambda f: abs(z[f]), reverse=True)
            results[r["cell_id"]] = {
                "layer": layer, "is_anomaly": anom, "score": float(score[i]),
                "score_percentile": float((score < score[i]).mean() * 100),
                "value": r.get(cfg["value"]), "direction": direction, "z_scores": z,
                "dominant_deviations": [{"feature": f, "label": LABELS[f], "z": round(z[f], 2),
                                         "direction": "above" if z[f] > 0 else "below",
                                         "value": None if r.get(f) is None else round(float(r[f]), 4)} for f in dom],
            }
        ML_DIR.mkdir(parents=True, exist_ok=True)
        joblib.dump({"model": model, "scaler": scaler, "features": feats}, ML_DIR / f"{cfg['model']}.joblib")
        out[layer] = {"status": "ok", "model": cfg["model"], "name": cfg["name"], "features": feats,
                      "feature_labels": [LABELS[f] for f in feats], "eligible": int(ok.sum()),
                      "anomalies": int((pred == -1).sum()), "unusually_high": int(high), "unusually_low": int(low),
                      "unusual_pattern": int(patchy), "contamination": IF_CONTAMINATION,
                      "local_radius_m": LOCAL_RADIUS_M, "results": results}
    return out


def run_station_isolation_forest(stations: list[dict]) -> dict[str, Any]:
    """Isolation Forest over real station pollutant sub-indices (no imputation)."""
    st = [s for s in stations if isinstance(s.get("sub_indices"), dict)]
    if len(st) < 8:
        return {"status": "insufficient", "eligible": len(st), "model": STATION_IF_MODEL,
                "reason": "needs >= 8 stations with pollutant sub-indices", "stations": []}
    present = [p for p in POLLUTANTS if np.mean([s["sub_indices"].get(p) is not None for s in st]) >= 0.7]
    rows = [s for s in st if all(s["sub_indices"].get(p) is not None for p in present)]
    if len(present) < 2 or len(rows) < 8:
        return {"status": "insufficient", "eligible": len(rows), "model": STATION_IF_MODEL,
                "reason": "too few stations report the same pollutants", "stations": []}
    X = np.array([[float(s["sub_indices"][p]) for p in present] for s in rows])
    contamination = max(0.05, min(0.2, 2.0 / len(rows)))
    _model, _scaler, Z, pred, score = _fit_if(X, contamination)
    res = []
    for i, s in enumerate(rows):
        z = {p: float(Z[i, j]) for j, p in enumerate(present)}
        dom = sorted(present, key=lambda p: abs(z[p]), reverse=True)[:3]
        res.append({"station_id": s.get("station_id"), "station_name": s.get("station_name"),
                    "lat": s.get("lat"), "lon": s.get("lon"), "aqi": s.get("aqi"),
                    "is_anomaly": bool(pred[i] == -1), "score_percentile": round(float((score < score[i]).mean() * 100), 1),
                    "dominant_deviations": [{"pollutant": POLLUTANT_LABELS[p], "sub_index": round(float(s["sub_indices"][p]), 1),
                                             "z": round(z[p], 2), "direction": "above" if z[p] > 0 else "below"} for p in dom]})
    return {"status": "ok", "model": STATION_IF_MODEL, "pollutants": [POLLUTANT_LABELS[p] for p in present],
            "eligible": len(rows), "anomalies": int((pred == -1).sum()), "contamination": round(contamination, 3),
            "stations": res}


def run_xgboost_lst(rows: list[dict]) -> dict[str, Any]:
    import xgboost as xgb

    X = _matrix(rows, XGB_FEATURES)
    y = np.array([r.get("lst_mean") if r.get("lst_mean") is not None else np.nan for r in rows])
    ok = np.all(np.isfinite(X), axis=1) & np.isfinite(y)
    if ok.sum() < 200:
        return {"status": "insufficient", "eligible": int(ok.sum()), "results": {}}
    Xo, yo = X[ok], y[ok]
    rows_ok = [r for r, k in zip(rows, ok) if k]
    groups = np.array([f"{int(r['lon'] // BLOCK_DEG)}_{int(r['lat'] // BLOCK_DEG)}" for r in rows_ok])
    params = dict(n_estimators=400, max_depth=4, learning_rate=0.05, subsample=0.8, colsample_bytree=0.9,
                  min_child_weight=5, reg_lambda=1.0, random_state=RANDOM_STATE, n_jobs=4)

    oof = np.zeros_like(yo)
    for tr, te in GroupKFold(n_splits=5).split(Xo, yo, groups):
        m = xgb.XGBRegressor(**params).fit(Xo[tr], yo[tr])
        oof[te] = m.predict(Xo[te])
    rmse = float(np.sqrt(mean_squared_error(yo, oof)))
    metrics = {"r2_spatial_cv": float(r2_score(yo, oof)), "rmse_c": rmse,
               "mae_c": float(mean_absolute_error(yo, oof)), "n_cells": int(ok.sum()),
               "cv": "GroupKFold(5) on ~3 km spatial blocks", "baseline_std_c": float(yo.std())}

    final = xgb.XGBRegressor(**params).fit(Xo, yo)
    final.get_booster().feature_names = list(XGB_FEATURES)
    contribs = final.get_booster().predict(xgb.DMatrix(Xo, feature_names=XGB_FEATURES), pred_contribs=True)
    gain = final.get_booster().get_score(importance_type="gain")
    tot = sum(gain.values()) or 1.0
    importance = {LABELS.get(f, f): round(gain.get(f, 0.0) / tot, 4) for f in XGB_FEATURES}

    results = {}
    for i, r in enumerate(rows_ok):
        resid = float(yo[i] - oof[i])
        c = {f: float(contribs[i, j]) for j, f in enumerate(XGB_FEATURES)}
        top = sorted(c, key=lambda f: abs(c[f]), reverse=True)[:3]
        flag = "unexplained_heat" if resid > 2 * rmse else "unexplained_cooling" if resid < -2 * rmse else "explained"
        results[r["cell_id"]] = {
            "observed_lst_c": round(float(yo[i]), 2),
            "expected_lst_c": round(float(oof[i]), 2),
            "residual_c": round(resid, 2),
            "flag": flag,
            "baseline_c": round(float(contribs[i, -1]), 2),
            "contributions_c": {LABELS[f]: round(c[f], 2) for f in XGB_FEATURES},
            "top_drivers": [{"feature": f, "label": LABELS[f], "effect_c": round(c[f], 2), "value": r.get(f)} for f in top],
        }
    ML_DIR.mkdir(parents=True, exist_ok=True)
    final.save_model(str(ML_DIR / f"{XGB_MODEL}.json"))
    return {"status": "ok", "metrics": metrics, "feature_importance_gain": importance, "features": XGB_FEATURES,
            "flags": {k: sum(1 for v in results.values() if v["flag"] == k)
                      for k in ("unexplained_heat", "unexplained_cooling", "explained")},
            "results": results, "xgboost_version": xgb.__version__}


def run_water_health(rows: list[dict]) -> dict[str, Any]:
    vals = [(r["cell_id"], r["wh_mean"]) for r in rows if r.get("wh_mean") is not None]
    if len(vals) < 30:
        return {"status": "insufficient", "eligible": len(vals), "results": {}}
    arr = np.array([v for _, v in vals])
    med = float(np.median(arr))
    mad = float(np.median(np.abs(arr - med))) * 1.4826 or 1e-6
    results = {}
    for cid, v in vals:
        z = (v - med) / mad
        results[cid] = {"wh_mean": round(v, 4), "robust_z": round(float(z), 2),
                        "percentile": round(float((arr < v).mean() * 100), 1),
                        "flag": "low_water_condition" if z < -2 else "high_water_condition" if z > 2 else "typical"}
    return {"status": "ok", "eligible": len(vals), "median": med, "mad_scaled": mad,
            "flags": {k: sum(1 for x in results.values() if x["flag"] == k)
                      for k in ("low_water_condition", "typical", "high_water_condition")},
            "results": results}


def persist_results(db, observed_at: datetime, iso: dict, xgbr: dict, wh: dict,
                    layers: dict | None = None) -> int:
    now = datetime.now(timezone.utc)
    payload = []
    for layer, lr in (layers or {}).items():
        for cid, r in lr.get("results", {}).items():
            top = ", ".join(f"{d['label']} {d['direction']} norm ({d['z']:+.1f}σ)" for d in r["dominant_deviations"][:2])
            word = {"high": "unusually high", "low": "unusually low", "pattern": "unusual pattern"}[r["direction"]]
            payload.append({"cid": cid, "score": r["score"], "flag": r["is_anomaly"], "model": lr["model"],
                            "atype": f"{layer}_{r['direction']}_outlier" if r["is_anomaly"] else f"{layer}_inlier",
                            "root": f"{lr['name']}: {word} ({top})." if r["is_anomaly"] else None,
                            "ev": {"model": lr["model"], "features": lr["features"], **r}})
    for cid, r in iso.get("results", {}).items():
        top = ", ".join(f"{d['label']} {d['direction']} city norm ({d['z']:+.1f}σ)" for d in r["dominant_deviations"][:2])
        payload.append({"cid": cid, "score": r["score"], "flag": r["is_anomaly"], "model": IF_MODEL,
                        "atype": "isolation_forest_spatial_anomaly" if r["is_anomaly"] else "isolation_forest_spatial_inlier",
                        "root": f"Multivariate outlier: {top}." if r["is_anomaly"] else None,
                        "ev": {"model": IF_MODEL, "features": iso["features"], **r}})
    for cid, r in xgbr.get("results", {}).items():
        payload.append({"cid": cid, "score": r["residual_c"], "flag": r["flag"] != "explained", "model": XGB_MODEL,
                        "atype": r["flag"],
                        "root": (f"Observed LST {r['observed_lst_c']}°C vs {r['expected_lst_c']}°C expected from land cover "
                                 f"(residual {r['residual_c']:+.1f}°C).") if r["flag"] != "explained" else None,
                        "ev": {"model": XGB_MODEL, "cv_metrics": xgbr["metrics"], **r}})
    for cid, r in wh.get("results", {}).items():
        payload.append({"cid": cid, "score": r["robust_z"], "flag": r["flag"] == "low_water_condition", "model": WH_MODEL,
                        "atype": r["flag"],
                        "root": (f"Water Health index {r['wh_mean']:.3f} is {abs(r['robust_z']):.1f} robust-σ below the "
                                 f"median of water cells.") if r["flag"] == "low_water_condition" else None,
                        "ev": {"model": WH_MODEL, "median": wh["median"], "mad_scaled": wh["mad_scaled"], **r}})
    for p in payload:
        p.update({"obs": observed_at, "det": now, "ev": json.dumps(p["ev"], default=float)})
    # Replace this snapshot's rows for these models so cells that are no longer
    # scored (e.g. water cells now excluded from Isolation Forest) keep no stale result.
    names = [IF_MODEL, XGB_MODEL, WH_MODEL] + [c["model"] for c in LAYER_IF.values()]
    db.execute(text("DELETE FROM anomaly_results WHERE observed_at = :obs AND model_name = ANY(:names)"),
               {"obs": observed_at, "names": names})
    if payload:
        db.execute(text("""
            INSERT INTO anomaly_results (cell_id, observed_at, detected_at, anomaly_score, is_anomaly, model_name,
                                         anomaly_type, root_cause, evidence, engineered_feature_id, environment_data_id)
            VALUES (:cid, :obs, :det, :score, :flag, :model, :atype, :root, CAST(:ev AS jsonb),
                    (SELECT id FROM engineered_features WHERE cell_id = :cid AND observed_at = :obs),
                    (SELECT id FROM environment_data WHERE cell_id = :cid AND observed_at = :obs))
            ON CONFLICT (cell_id, observed_at, model_name) DO UPDATE SET
                detected_at = EXCLUDED.detected_at, anomaly_score = EXCLUDED.anomaly_score,
                is_anomaly = EXCLUDED.is_anomaly, anomaly_type = EXCLUDED.anomaly_type,
                root_cause = EXCLUDED.root_cause, evidence = EXCLUDED.evidence
        """), payload)
    return len(payload)


DISTRIBUTION_FEATURES = ["ndvi_mean", "veg_frac", "built_frac", "lst_mean", "wh_mean", "aqi_idw", "dist_water_m"]


def city_distributions(rows: list[dict]) -> dict[str, list[float]]:
    """Per-feature 0..100 percentile tables across all cells (for 'how unusual is this cell')."""
    out = {}
    for f in DISTRIBUTION_FEATURES:
        v = np.array([r[f] for r in rows if r.get(f) is not None], dtype="float64")
        if v.size >= 30:
            out[f] = [round(float(x), 5) for x in np.percentile(v, np.arange(101))]
    return out


def write_summary(observed_at: datetime, sources: dict, iso: dict, xgbr: dict, wh: dict, n_cells: int,
                  rows: list[dict] | None = None, layers: dict | None = None, stations: dict | None = None) -> Path:
    import xgboost as xgb
    summary = {
        "snapshot_at": observed_at.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cells_total": n_cells,
        "city_percentiles": city_distributions(rows or []),
        "sources": sources,
        "isolation_forest": {k: v for k, v in iso.items() if k != "results"} | {"model": IF_MODEL, "sklearn": sklearn_version},
        "xgboost_lst": {k: v for k, v in xgbr.items() if k != "results"} | {"model": XGB_MODEL, "xgboost": xgb.__version__},
        "water_health": {k: v for k, v in wh.items() if k != "results"} | {"model": WH_MODEL},
        "layer_isolation_forest": {k: {kk: vv for kk, vv in v.items() if kk != "results"}
                                   for k, v in (layers or {}).items()},
        "station_isolation_forest": stations or {"status": "not_run"},
        "caveats": [
            "Signals are statistical associations within one snapshot, not causal proof.",
            "LST cells with <30% cloud-free Landsat pixels are excluded rather than filled.",
            "Water Health is a satellite spectral proxy, not laboratory water quality.",
            "AQI enters the models only when a real OpenAQ CPCB/MPCB station surface exists.",
        ],
    }
    ML_DIR.mkdir(parents=True, exist_ok=True)
    p = ML_DIR / "ml_summary.json"
    p.write_text(json.dumps(summary, indent=2, default=float), encoding="utf-8")
    return p
