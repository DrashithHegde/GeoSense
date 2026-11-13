"""Ground-truth checks against independent references.

1. ESA WorldCover 2021 (10 m, independent land-cover map) vs GeoSense's own cell shares:
   vegetation, built/bare and water — rank agreement and dominant-class agreement.
2. Physical plausibility of LST: median surface temperature by WorldCover class
   (built-up/bare should be hotter than trees, mangroves and water).
3. Where the heat flags fall: share of "unexplained heat" / unusually-hot cells that are
   built-up or bare in WorldCover, against the base rate.
4. AQI: leave-one-station-out error of the IDW surface (from the AQI manifest record).

These are agreement checks with an independent product, not proof: WorldCover has its own
errors (reported overall accuracy about 77% globally, Zanaga et al. 2022) and is from 2021.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import spearmanr

SERVER_ROOT = Path(__file__).resolve().parents[3]
WORLDCOVER_CSV = SERVER_ROOT / "data" / "validation" / "worldcover_cells_v200.csv"
WORLDCOVER_CLASSES = {10: "tree", 20: "shrub", 30: "grass", 40: "crop", 50: "built", 60: "bare",
                      70: "snow", 80: "water", 90: "wetland", 95: "mangrove", 100: "moss"}
# our broad classes <- WorldCover classes
BROAD = {"vegetation": ("tree", "shrub", "grass", "crop", "mangrove", "wetland"),
         "built/bare": ("built", "bare"), "water": ("water",)}


def load_worldcover(path: Path = WORLDCOVER_CSV) -> dict[int, dict[str, float]]:
    if not path.exists():
        return {}
    out = {}
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[int(r["cell_id"])] = {k[3:]: float(v) for k, v in r.items() if k.startswith("wc_") and v not in ("", "None")}
    return out


def _wc_share(wc: dict[str, float], names) -> float:
    return float(sum(wc.get(n, 0.0) for n in names))


def _dominant(wc: dict[str, float]) -> str | None:
    shares = {b: _wc_share(wc, names) for b, names in BROAD.items()}
    b, v = max(shares.items(), key=lambda kv: kv[1])
    return b if v >= 0.5 else "mixed"


def _ours(r: dict) -> str | None:
    ow, veg, built = r.get("openwater_frac"), r.get("veg_frac"), r.get("built_frac")
    if ow is None or veg is None or built is None:
        return None
    # our NDVI shares: vegetation = NDVI >= 0.5 (dense) — use moderately green (>=0.2) as "vegetation" here
    land_green = 1.0 - ow - built
    shares = {"water": ow, "built/bare": built, "vegetation": land_green}
    b, v = max(shares.items(), key=lambda kv: kv[1])
    return b if v >= 0.5 else "mixed"


def _agree(xs, ys) -> dict | None:
    a = np.array([(x, y) for x, y in zip(xs, ys) if x is not None and y is not None], dtype=float)
    if len(a) < 30:
        return None
    return {"n": int(len(a)), "spearman_rho": round(float(spearmanr(a[:, 0], a[:, 1])[0]), 3),
            "mean_abs_diff": round(float(np.abs(a[:, 0] - a[:, 1]).mean()), 3)}


def compute_validation(rows: list[dict], xgb_results: dict | None = None, lst_layer: dict | None = None,
                       aqi_record: dict | None = None, wc: dict[int, dict[str, float]] | None = None) -> dict[str, Any]:
    wc = load_worldcover() if wc is None else wc
    out: dict[str, Any] = {"worldcover": {"status": "not_run",
                                          "how": "python scripts/build_validation_reference.py (Earth Engine)"}}
    if wc:
        joined = [(r, wc[r["cell_id"]]) for r in rows if r["cell_id"] in wc]
        veg = _agree([r.get("veg_frac") for r, _ in joined], [_wc_share(w, ("tree", "mangrove")) for _, w in joined])
        green = _agree([None if r.get("built_frac") is None or r.get("openwater_frac") is None
                        else 1 - r["built_frac"] - r["openwater_frac"] for r, _ in joined],
                       [_wc_share(w, BROAD["vegetation"]) for _, w in joined])
        built = _agree([r.get("built_frac") for r, _ in joined], [_wc_share(w, BROAD["built/bare"]) for _, w in joined])
        ndbi = _agree([r.get("ndbi_land_mean") for r, _ in joined], [_wc_share(w, BROAD["built/bare"]) for _, w in joined])
        water = _agree([r.get("openwater_frac") for r, _ in joined], [_wc_share(w, ("water",)) for _, w in joined])
        pairs = [(_ours(r), _dominant(w)) for r, w in joined]
        pairs = [(a, b) for a, b in pairs if a and b]
        classes = sorted({b for _, b in pairs})
        confusion = {o: {w: sum(1 for a, b in pairs if a == o and b == w) for w in classes} for o in classes}
        dom_agree = round(100 * sum(a == b for a, b in pairs) / len(pairs), 1) if pairs else None

        # LST by WorldCover dominant class
        by_cls: dict[str, list[float]] = {}
        for r, w in joined:
            if r.get("lst_mean") is None:
                continue
            cls = max(w.items(), key=lambda kv: kv[1])[0] if w else None
            if cls and w[cls] >= 0.5:
                by_cls.setdefault(cls, []).append(r["lst_mean"])
        lst_cls = {c: {"n": len(v), "median_c": round(float(np.median(v)), 1),
                       "iqr_c": [round(float(np.percentile(v, 25)), 1), round(float(np.percentile(v, 75)), 1)]}
                   for c, v in by_cls.items() if len(v) >= 30}
        plaus = None
        if "built" in lst_cls and ("tree" in lst_cls or "water" in lst_cls):
            cool = [lst_cls[c]["median_c"] for c in ("tree", "water", "mangrove") if c in lst_cls]
            plaus = lst_cls["built"]["median_c"] > max(cool)

        # where do heat flags fall?
        def in_built(ids):
            hits = [_wc_share(wc[i], BROAD["built/bare"]) >= 0.5 for i in ids if i in wc]
            return (round(100 * sum(hits) / len(hits), 1), len(hits)) if hits else (None, 0)

        base_pct, base_n = in_built([r["cell_id"] for r in rows if r.get("lst_mean") is not None])
        heat_ids = [cid for cid, v in (xgb_results or {}).items() if v.get("flag") == "unexplained_heat"]
        hot_ids = [cid for cid, v in ((lst_layer or {}).get("results") or {}).items()
                   if v.get("is_anomaly") and v.get("direction") == "high"]
        hp, hn = in_built(heat_ids)
        lp, ln = in_built(hot_ids)
        out["worldcover"] = {
            "status": "ok", "reference": "ESA WorldCover 2021 v200 (10 m), independent of GeoSense",
            "cells_compared": len(joined),
            "vegetation_dense_vs_tree_mangrove": veg, "vegetation_any_vs_wc_vegetation": green,
            "built_bare_share": built, "ndbi_vs_built_bare": ndbi, "open_water_share": water,
            "dominant_class_agreement_pct": dom_agree, "dominant_class_confusion": confusion,
            "lst_by_worldcover_class": lst_cls, "lst_physically_plausible": plaus,
            "heat_flags_in_built_bare_pct": {"base_rate": base_pct, "unexplained_heat": hp, "unexplained_heat_n": hn,
                                             "lst_isolation_forest_high": lp, "lst_isolation_forest_high_n": ln},
            "caveat": "WorldCover has its own errors (about 77% overall accuracy globally) and is from 2021; "
                      "agreement is evidence of consistency, not proof.",
        }
    v = (aqi_record or {}).get("validation")
    if v is None and (aqi_record or {}).get("stations"):
        from app.services.surfaces.aqi_station_surface import loso_validation
        v = loso_validation(aqi_record["stations"])
    out["aqi_idw_loso"] = ({k: v.get(k) for k in ("status", "method", "n", "mae", "rmse", "bias",
                                                    "category_agreement_pct", "by_distance")} if v else
                           {"status": "not_run", "reason": "no AQI station surface"})
    return out
