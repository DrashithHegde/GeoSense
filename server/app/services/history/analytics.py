"""Seasonal history analytics: what changed, how unusual the change is, what persists.

* Same-season, year-on-year change only (compatible windows; partial seasons use a matched
  window one year earlier).
* Sudden change: modified z-score of a cell's change against all cells' changes for the same
  season pair (Iglewicz & Hoaglin 1993, |z| >= 3.5), AND a minimum physical change so tiny
  shifts are never flagged.
* Persistence: in how many full seasons a cell sat in the hottest 10% (LST) / least green 10%
  (NDVI) / lowest 10% water condition (Water Health) of that season.
* Trend: Theil-Sen slope per year over the same season, only with >= 4 full seasons, and
  reported as indicative.
* Change-aware Isolation Forest: unusual combinations of changes (LST, NDVI, NDMI) between the
  latest comparable pair.
Missing seasons (cloud) stay missing; nothing is interpolated in time.
"""
from __future__ import annotations
from app.core.cities import city_path

import json
from typing import Any

import numpy as np
from sqlalchemy import text

from app.core.cities import current_city_id, get_city
from app.services.history.gee_builder import HISTORY_DIR

SUMMARY_PATH = city_path("history", "history_summary.json")
CHANGE_IF_PATH = city_path("history", "change_if.json")
METRICS = {
    "lst": {"label": "LST", "unit": "°C", "min_change": 2.0, "persist": ("high", "hottest 10%")},
    "ndvi": {"label": "NDVI", "unit": "", "min_change": 0.10, "persist": ("low", "least green 10%")},
    "ndmi_veg": {"label": "vegetation moisture (NDMI)", "unit": "", "min_change": 0.08, "persist": None},
    "wh": {"label": "Water Health", "unit": "", "min_change": 0.05, "persist": ("low", "lowest 10% water condition")},
    "ndbi_land": {"label": "built-up index (NDBI)", "unit": "", "min_change": 0.08, "persist": None},
}
MODZ = 0.6745
SUDDEN_Z = 3.5
CHANGE_IF_FEATURES = ["d_lst", "d_ndvi", "d_ndmi_veg"]


def _seasons(db) -> list[dict[str, Any]]:
    rows = db.execute(text("SELECT season, label, kind, year, period_start, period_end, partial, s2_images, "
                           "landsat_images, metadata FROM history_seasons WHERE city = :city ORDER BY period_start"),
                      {"city": current_city_id()}).mappings().all()
    out = []
    for r in rows:
        meta = r["metadata"] or {}
        out.append({"season": r["season"], "label": r["label"], "kind": r["kind"], "year": r["year"],
                    "period_start": r["period_start"].isoformat(), "period_end": r["period_end"].isoformat(),
                    "partial": r["partial"], "matched_for": meta.get("matched_for"),
                    "s2_images": r["s2_images"], "landsat_images": r["landsat_images"]})
    return out


def comparable(season: dict, by_key: dict[str, dict]) -> dict | None:
    if season.get("matched_for"):
        return None
    prev = f"{season['year'] - 1}-{season['kind']}" + ("-matched" if season["partial"] else "")
    return by_key.get(prev)


def _modz(x: np.ndarray) -> tuple[float, float]:
    med = float(np.median(x))
    mad = float(np.median(np.abs(x - med)))
    return med, mad


def theil_sen(years: list[int], vals: list[float]) -> float | None:
    if len(vals) < 4:
        return None
    slopes = [(vals[j] - vals[i]) / (years[j] - years[i])
              for i in range(len(vals)) for j in range(i + 1, len(vals)) if years[j] != years[i]]
    return float(np.median(slopes)) if slopes else None


def build_summary(db) -> dict[str, Any]:
    """Region-wide tables used at request time (percentiles per season, change distributions)."""
    seasons = _seasons(db)
    by_key = {s["season"]: s for s in seasons}
    data: dict[str, dict[int, dict[str, float]]] = {}
    for s in seasons:
        rows = db.execute(text(f"SELECT cell_id, {', '.join(METRICS)} FROM cell_history "
                               "WHERE city = :city AND season = :s"),
                          {"city": current_city_id(), "s": s["season"]}).mappings().all()
        data[s["season"]] = {r["cell_id"]: {m: r[m] for m in METRICS} for r in rows}
    pct: dict[str, dict[str, list[float]]] = {}
    for key, cells in data.items():
        pct[key] = {}
        for m in METRICS:
            v = np.array([c[m] for c in cells.values() if c[m] is not None], dtype=float)
            if v.size >= 100:
                pct[key][m] = [round(float(x), 5) for x in np.percentile(v, np.arange(101))]
    changes: dict[str, dict[str, Any]] = {}
    latest_pair = None
    for s in seasons:
        prev = comparable(s, by_key)
        if not prev or prev["season"] not in data:
            continue
        pair = f"{s['season']}|{prev['season']}"
        changes[pair] = {}
        for m in METRICS:
            a, b = data[s["season"]], data[prev["season"]]
            d = np.array([a[c][m] - b[c][m] for c in a if c in b and a[c][m] is not None and b[c][m] is not None])
            if d.size >= 100:
                med, mad = _modz(d)
                changes[pair][m] = {"n": int(d.size), "median": round(med, 4), "mad": round(mad, 5)}
        latest_pair = (s, prev)
    summary = {"seasons": seasons, "percentiles": pct, "changes": changes,
               "latest_pair": [latest_pair[0]["season"], latest_pair[1]["season"]] if latest_pair else None,
               "method": __doc__.strip().splitlines()[0]}
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    change_if = run_change_isolation_forest(data, latest_pair) if latest_pair else {"status": "no comparable pair"}
    CHANGE_IF_PATH.write_text(json.dumps(change_if, default=float), encoding="utf-8")
    summary["change_isolation_forest"] = {k: v for k, v in change_if.items() if k != "results"}
    SUMMARY_PATH.write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    return summary


def run_change_isolation_forest(data: dict, pair) -> dict[str, Any]:
    from sklearn.ensemble import IsolationForest

    cur, prev = pair
    a, b = data[cur["season"]], data[prev["season"]]
    ids, X = [], []
    for cid, v in a.items():
        p = b.get(cid)
        if not p:
            continue
        row = [None if v[m] is None or p[m] is None else v[m] - p[m] for m in ("lst", "ndvi", "ndmi_veg")]
        if row[0] is None or row[1] is None:
            continue
        ids.append(cid)
        X.append([np.nan if x is None else x for x in row])
    if len(ids) < 200:
        return {"status": "insufficient", "eligible": len(ids)}
    X = np.array(X, dtype=float)
    # NDMI change only exists for vegetated cells: fall back to the 2-feature model if too sparse
    feats = CHANGE_IF_FEATURES if np.isfinite(X[:, 2]).mean() >= 0.6 else CHANGE_IF_FEATURES[:2]
    Xf = X[:, :len(feats)]
    keep = np.all(np.isfinite(Xf), axis=1)
    Xk = Xf[keep]
    ids_k = [i for i, k in zip(ids, keep) if k]
    med = np.median(Xk, axis=0)
    mad = np.median(np.abs(Xk - med), axis=0)
    mad[mad == 0] = 1e-9
    model = IsolationForest(n_estimators=300, contamination=0.02, random_state=42).fit(Xk)
    pred = model.predict(Xk)
    score = -model.score_samples(Xk)
    res = {}
    for i, cid in enumerate(ids_k):
        z = MODZ * (Xk[i] - med) / mad
        res[str(cid)] = {"is_anomaly": bool(pred[i] == -1), "score": round(float(score[i]), 4),
                         "changes": {f: round(float(Xk[i, j]), 3) for j, f in enumerate(feats)},
                         "z": {f: round(float(z[j]), 2) for j, f in enumerate(feats)}}
    return {"status": "ok", "pair": [cur["season"], prev["season"]], "features": feats, "eligible": len(ids_k),
            "anomalies": int((pred == -1).sum()), "contamination": 0.02, "results": res}


def _pct_of(table: list[float] | None, v: float | None) -> float | None:
    if table is None or v is None:
        return None
    return float(np.interp(v, table, np.arange(101)))


def cell_history(db, cell_id: int, lat: float | None = None, lon: float | None = None,
                 summary: dict | None = None, change_if: dict | None = None) -> dict[str, Any] | None:
    """Everything Deep Analysis needs about one cell's past."""
    if summary is None:
        if not SUMMARY_PATH.exists():
            return None
        summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    seasons = summary.get("seasons") or []
    if not seasons:
        return None
    by_key = {s["season"]: s for s in seasons}
    rows = db.execute(text(f"SELECT season, {', '.join(METRICS)}, s2_valid_frac, lst_valid_frac "
                           "FROM cell_history WHERE cell_id = :c AND city = :city"),
                      {"c": cell_id, "city": current_city_id()}).mappings().all()
    vals = {r["season"]: dict(r) for r in rows}
    shown = [s for s in seasons if not s.get("matched_for")]
    out: dict[str, Any] = {"seasons": [{k: s[k] for k in ("season", "label", "kind", "year", "partial",
                                                           "period_start", "period_end")} for s in shown],
                           "metrics": {}, "station": None, "method": summary.get("method")}
    for m, meta in METRICS.items():
        series = [{"season": s["season"], "label": s["label"], "kind": s["kind"], "year": s["year"],
                   "partial": s["partial"], "value": None if (vals.get(s["season"]) or {}).get(m) is None
                   else round(float(vals[s["season"]][m]), 3)} for s in shown]
        if not any(p["value"] is not None for p in series):
            continue
        entry: dict[str, Any] = {"label": meta["label"], "unit": meta["unit"], "series": series,
                                 "missing": [p["label"] for p in series if p["value"] is None]}
        # latest comparable same-season change
        for s in reversed(shown):
            prev = comparable(s, by_key)
            cur_v = (vals.get(s["season"]) or {}).get(m)
            prev_v = (vals.get(prev["season"]) or {}).get(m) if prev else None
            if prev is None or cur_v is None or prev_v is None:
                continue
            d = float(cur_v) - float(prev_v)
            dist = (summary.get("changes") or {}).get(f"{s['season']}|{prev['season']}", {}).get(m)
            z = None
            if dist and dist["mad"] > 0:
                z = MODZ * (d - dist["median"]) / dist["mad"]
            entry["change"] = {"from": prev["label"], "to": s["label"], "delta": round(d, 3),
                               "modified_z": None if z is None else round(z, 1),
                               "sudden": bool(z is not None and abs(z) >= SUDDEN_Z and abs(d) >= meta["min_change"]),
                               "region_median_delta": None if not dist else dist["median"]}
            break
        # persistence across full seasons
        if meta["persist"]:
            side, words = meta["persist"]
            hits, n = 0, 0
            for s in shown:
                if s["partial"]:
                    continue
                p = _pct_of(((summary.get("percentiles") or {}).get(s["season"]) or {}).get(m),
                            (vals.get(s["season"]) or {}).get(m))
                if p is None:
                    continue
                n += 1
                hits += int(p >= 90 if side == "high" else p <= 10)
            if n:
                entry["persistence"] = {"seasons_flagged": hits, "seasons_observed": n, "description": words,
                                        "persistent": hits >= 3 and hits / n >= 0.6}
        # trend over the same season (indicative)
        for kind in get_city().seasons:
            pts = [(s["year"], (vals.get(s["season"]) or {}).get(m)) for s in shown
                   if s["kind"] == kind and not s["partial"]]
            pts = [(y, float(v)) for y, v in pts if v is not None]
            slope = theil_sen([y for y, _ in pts], [v for _, v in pts])
            if slope is not None:
                entry.setdefault("trend", {})[kind] = {"per_year": round(slope, 3), "seasons": len(pts),
                                                       "note": "indicative: few seasons"}
        out["metrics"][m] = entry
    ci = change_if if change_if is not None else (
        json.loads(CHANGE_IF_PATH.read_text(encoding="utf-8")) if CHANGE_IF_PATH.exists() else {})
    r = (ci.get("results") or {}).get(str(cell_id))
    if r:
        out["change_isolation_forest"] = {"pair": ci.get("pair"), **r}
    if lat is not None and lon is not None:
        out["station"] = nearest_station_history(db, lat, lon, by_key)
    return out


def nearest_station_history(db, lat: float, lon: float, by_key: dict[str, dict], max_km: float = 10.0):
    rows = db.execute(text("SELECT station_id, station_name, lat, lon, season, days_with_aqi, aqi_median, aqi_p90, "
                           "dominant_pollutant, method FROM station_aqi_history WHERE city = :city"),
                      {"city": current_city_id()}).mappings().all()
    if not rows:
        return None
    from app.services.surfaces.aqi_station_surface import _haversine_m
    dist = {}
    for r in rows:
        dist.setdefault(r["station_id"], _haversine_m(lat, lon, r["lat"], r["lon"]))
    sid = min(dist, key=dist.get)
    if dist[sid] > max_km * 1000:
        return None
    mine = {r["season"]: r for r in rows if r["station_id"] == sid}
    any_r = next(iter(mine.values()))
    series = [{"season": s["season"], "label": s["label"], "partial": s["partial"],
               "aqi_median": (mine.get(s["season"]) or {}).get("aqi_median"),
               "days": (mine.get(s["season"]) or {}).get("days_with_aqi")}
              for s in by_key.values() if not s.get("matched_for")]
    out = {"station_name": any_r["station_name"], "distance_m": round(dist[sid]), "series": series,
           "method": any_r["method"]}
    for s in reversed([s for s in by_key.values() if not s.get("matched_for")]):
        prev = comparable(s, by_key)
        a, b = mine.get(s["season"]), mine.get(prev["season"]) if prev else None
        if a and b and a["aqi_median"] is not None and b["aqi_median"] is not None:
            out["change"] = {"from": prev["label"], "to": s["label"],
                             "delta": round(a["aqi_median"] - b["aqi_median"], 1)}
            break
    return out
