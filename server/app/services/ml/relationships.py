"""Cross-indicator relationships across the 300 m cells (internal, explanatory).

Pearson r (linear) and Spearman rho (monotonic) for indicator pairs, per municipality and per
broad land-cover class. Used to word explanations ("greener cells are usually cooler here")
and shown as one line in the City Model Cards — not a statistics dashboard.

Honest limits, stored with the results:
* Neighbouring cells are not independent (spatial autocorrelation), so classical p-values
  would be far too small; we report effect sizes and n, not significance.
* AQI between stations is interpolated from a handful of stations, so its effective sample
  size is the station count, not the cell count. AQI pairs are marked accordingly.
* Correlation is association, never causation.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from scipy.stats import pearsonr, spearmanr

# (x, y, scope) — scope "land": cells that are mostly land; "water": cells with a Water Health value
PAIRS: list[tuple[str, str, str]] = [
    ("ndvi_mean", "lst_mean", "land"),
    ("veg_frac", "lst_mean", "land"),
    ("built_frac", "lst_mean", "land"),
    ("ndbi_land_mean", "lst_mean", "land"),
    ("ndmi_veg_mean", "lst_mean", "land"),
    ("ndvi_mean", "aqi_idw", "land"),
    ("lst_mean", "aqi_idw", "land"),
    ("wh_mean", "lst_mean", "water"),
    ("wh_mean", "aqi_idw", "water"),
    ("wh_mean", "ndvi_land_mean", "water"),
]
LABEL = {"ndvi_mean": "NDVI", "veg_frac": "dense-vegetation share", "built_frac": "built/bare share",
         "ndbi_land_mean": "NDBI", "ndmi_veg_mean": "NDMI (vegetation moisture)", "lst_mean": "LST",
         "aqi_idw": "AQI (interpolated)", "wh_mean": "Water Health", "ndvi_land_mean": "NDVI of surrounding land"}
MIN_N = 30


def _strength(rho: float) -> str:
    a = abs(rho)
    return "strong" if a >= 0.6 else "moderate" if a >= 0.4 else "weak" if a >= 0.2 else "negligible"


def land_class(r: dict) -> str | None:
    v, b = r.get("veg_frac"), r.get("built_frac")
    if v is None or b is None or (r.get("openwater_frac") or 0) >= 0.5:
        return None
    return "vegetation-dominated" if v >= 0.5 else "built-up-dominated" if b >= 0.5 else "mixed"


def _pair(rows: list[dict], x: str, y: str) -> dict[str, Any] | None:
    a = np.array([[r.get(x), r.get(y)] for r in rows if r.get(x) is not None and r.get(y) is not None], dtype=float)
    if len(a) < MIN_N or np.std(a[:, 0]) == 0 or np.std(a[:, 1]) == 0:
        return None
    pr = float(pearsonr(a[:, 0], a[:, 1])[0])
    sr = float(spearmanr(a[:, 0], a[:, 1])[0])
    return {"n": int(len(a)), "pearson_r": round(pr, 3), "spearman_rho": round(sr, 3), "strength": _strength(sr),
            "direction": "positive" if sr > 0 else "negative"}


def compute_relationships(rows: list[dict], n_stations: int | None = None) -> dict[str, Any]:
    land = [r for r in rows if (r.get("openwater_frac") or 0) < 0.5]
    water = [r for r in rows if r.get("wh_mean") is not None]
    scopes = {"land": land, "water": water}
    munis = sorted({r.get("municipality") for r in rows if r.get("municipality")})
    out: dict[str, Any] = {"pairs": [], "notes": [
        "Effect sizes only: neighbouring cells are spatially autocorrelated, so p-values are not reported.",
        "Association, not causation.",
    ]}
    for x, y, scope in PAIRS:
        base = scopes[scope]
        overall = _pair(base, x, y)
        if overall is None:
            continue
        entry = {"x": x, "y": y, "label": f"{LABEL[x]} ↔ {LABEL[y]}", "scope": scope, "all": overall,
                 "by_municipality": {m: _pair([r for r in base if r.get("municipality") == m], x, y) for m in munis},
                 "by_land_class": {}}
        if scope == "land":
            for c in ("vegetation-dominated", "mixed", "built-up-dominated"):
                entry["by_land_class"][c] = _pair([r for r in base if land_class(r) == c], x, y)
        if "aqi_idw" in (x, y):
            entry["caution"] = (f"AQI between stations is interpolated from {n_stations or 'a few'} stations; the "
                                "effective sample size is the station count, so treat this as indicative only.")
        out["pairs"].append(entry)
    return out


def headline(rel: dict | None, x: str, y: str) -> dict | None:
    for p in (rel or {}).get("pairs") or []:
        if p["x"] == x and p["y"] == y:
            return p["all"]
    return None
