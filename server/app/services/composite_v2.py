"""Composite Environmental Stress v2 — documented, coverage-aware, decomposable.

Three components, each scaled so that 0 = least and 1 = most concern:

  heat     Landsat LST (QC-passed), scaled by the study region's 5th..95th percentile.
  surface  "surface condition" — the land/water half of the picture, one slot so the two are
           never added together for the same pixel:
             land pixels  (NDVI >= 0): vegetation deficit = 1 - clip(NDVI / 0.8)
             water pixels (NDVI <  0): water-condition deficit from Water Health, scaled by the
                                       water pixels' 5th..95th percentile (higher WH = less stress)
  air      CPCB AQI / 300 from the station IDW surface, only where it exists.

Weights (heat 0.40, surface 0.35, air 0.25) are the project's documented expert weights,
carried over unchanged so the map does not shift meaning; their influence is checked with a
sensitivity analysis (alternative weightings + ranking stability), following the OECD/JRC
Handbook on Constructing Composite Indicators (2008). Supporting indices (NDMI, NDBI) are NOT
added: NDBI = -NDMI and both overlap NDVI/LST, so adding them would double-count.

Missing data: a pixel needs at least 2 of the 3 components; weights are renormalised over the
components it has, and the coverage is stored. Missing is never treated as zero or healthy.
"""
from __future__ import annotations

from typing import Any

import numpy as np

WEIGHTS = {"heat": 0.40, "surface": 0.35, "air": 0.25}
COMPONENTS = ("heat", "surface", "air")
MIN_COMPONENTS = 2
NDVI_FULL = 0.8
ALTERNATIVE_WEIGHTS = {
    "equal": {"heat": 1 / 3, "surface": 1 / 3, "air": 1 / 3},
    "heat-heavy": {"heat": 0.55, "surface": 0.25, "air": 0.20},
    "surface-heavy": {"heat": 0.30, "surface": 0.50, "air": 0.20},
    "air-heavy": {"heat": 0.30, "surface": 0.30, "air": 0.40},
}
METHOD_NOTE = ("Heat (LST), surface condition (vegetation deficit on land, Water Health deficit on water) and air "
               "(CPCB AQI) scaled 0-1; weights 0.40/0.35/0.25 renormalised over the components present; at least "
               "2 of 3 required. GeoSense-derived analytical index, not an official government index.")
CITATION = ("OECD/JRC (2008). Handbook on Constructing Composite Indicators: Methodology and User Guide. "
            "OECD Publishing, Paris.")


def compute_components(lst: np.ndarray, ndvi: np.ndarray, wh: np.ndarray | None, aqi: np.ndarray | None,
                       region: np.ndarray) -> dict[str, Any]:
    """All inputs on one grid; NaN = missing. Returns scaled components (NaN where missing)."""
    heat = np.full(lst.shape, np.nan, dtype="float32")
    ok = np.isfinite(lst) & region
    p5, p95 = (np.nanpercentile(lst[ok], [5, 95]) if ok.any() else (np.nan, np.nan))
    if ok.any() and p95 > p5:
        heat[ok] = np.clip((lst[ok] - p5) / (p95 - p5), 0, 1)

    surface = np.full(lst.shape, np.nan, dtype="float32")
    land = np.isfinite(ndvi) & (ndvi >= 0) & region
    surface[land] = 1.0 - np.clip(ndvi[land] / NDVI_FULL, 0, 1)
    wh_scale = None
    if wh is not None:
        water = np.isfinite(wh) & np.isfinite(ndvi) & (ndvi < 0) & region
        if water.sum() >= 30:
            w5, w95 = np.percentile(wh[water], [5, 95])
            if w95 > w5:
                surface[water] = np.clip((w95 - wh[water]) / (w95 - w5), 0, 1)
                wh_scale = {"p5": float(w5), "p95": float(w95)}

    air = np.full(lst.shape, np.nan, dtype="float32")
    if aqi is not None:
        a = np.isfinite(aqi) & region
        air[a] = np.clip(aqi[a] / 300.0, 0, 1)
    return {"heat": heat, "surface": surface, "air": air,
            "scaling": {"lst_c": {"p5": float(p5), "p95": float(p95)}, "water_health": wh_scale, "aqi_max": 300.0}}


def combine(comps: dict[str, np.ndarray], weights: dict[str, float] = WEIGHTS,
            min_components: int = MIN_COMPONENTS) -> tuple[np.ndarray, np.ndarray]:
    """Weighted mean over the components present; returns (score with NaN, coverage count)."""
    stack = np.stack([comps[k] for k in COMPONENTS])
    present = np.isfinite(stack)
    cover = present.sum(axis=0)
    w = np.array([weights[k] for k in COMPONENTS], dtype="float64")[:, None, None] * present
    with np.errstate(invalid="ignore", divide="ignore"):
        score = np.nansum(np.where(present, stack, 0) * w, axis=0) / w.sum(axis=0)
    score = np.where(cover >= min_components, score, np.nan).astype("float32")
    return score, cover.astype("uint8")


def contributions(values: dict[str, float | None], weights: dict[str, float] = WEIGHTS) -> dict[str, Any] | None:
    """Per-location breakdown: each component's share of the score (renormalised weights)."""
    have = {k: v for k, v in values.items() if k in COMPONENTS and v is not None and np.isfinite(v)}
    if len(have) < MIN_COMPONENTS:
        return None
    ws = sum(weights[k] for k in have)
    parts = {k: weights[k] / ws * v for k, v in have.items()}
    score = sum(parts.values())
    return {"score": round(score, 3), "coverage": f"{len(have)} of {len(COMPONENTS)}",
            "components": {k: {"value": round(v, 3), "weight": round(weights[k] / ws, 3),
                               "points": round(parts[k], 3),
                               "share_pct": round(100 * parts[k] / score, 0) if score > 0 else 0.0}
                           for k, v in have.items()},
            "missing": [k for k in COMPONENTS if k not in have]}


def sensitivity(comps: dict[str, np.ndarray], top_fraction: float = 0.10, sample: int | None = 200_000,
                seed: int = 0) -> dict[str, Any]:
    """How much do rankings change under alternative weightings? (spec: test weighting sensitivity)"""
    from scipy.stats import spearmanr

    base, _ = combine(comps)
    idx = np.flatnonzero(np.isfinite(base.ravel()))
    if idx.size < 50:
        return {"status": "insufficient"}
    if sample and idx.size > sample:
        idx = np.random.default_rng(seed).choice(idx, sample, replace=False)
    b = base.ravel()[idx]
    k = max(1, int(len(b) * top_fraction))
    top_b = set(np.argsort(-b)[:k])
    out = {"status": "ok", "n": int(len(b)), "top_fraction": top_fraction, "alternatives": {}}
    always = set(top_b)
    for name, w in ALTERNATIVE_WEIGHTS.items():
        alt, _ = combine(comps, w)
        a = alt.ravel()[idx]
        top_a = set(np.argsort(-a)[:k])
        always &= top_a
        out["alternatives"][name] = {"weights": {kk: round(vv, 3) for kk, vv in w.items()},
                                     "spearman_vs_base": round(float(spearmanr(b, a)[0]), 3),
                                     "top_overlap_pct": round(100 * len(top_b & top_a) / k, 1)}
    out["top_stable_pct"] = round(100 * len(always) / k, 1)
    out["summary"] = (f"{out['top_stable_pct']:.0f}% of the top-{int(top_fraction * 100)}% most stressed locations stay in the "
                      f"top {int(top_fraction * 100)}% under all {len(ALTERNATIVE_WEIGHTS)} alternative weightings; rank "
                      f"correlation with the base weights is "
                      f"{min(v['spearman_vs_base'] for v in out['alternatives'].values()):.2f} or higher.")
    return out


def read_components_pixel(lon: float, lat: float, manifest_path) -> dict[str, Any] | None:
    """Exact component values at a point from the components GeoTIFF + the renormalised breakdown."""
    import json
    from pathlib import Path

    import rasterio
    from rasterio.windows import Window

    manifest_path = Path(manifest_path)
    rec = (json.loads(manifest_path.read_text(encoding="utf-8")).get("surfaces") or {}).get("composite") or {}
    rel = rec.get("components_filename")
    if not rel or not (manifest_path.parent / rel).exists():
        return None
    with rasterio.open(manifest_path.parent / rel) as ds:
        b = ds.bounds
        if not (b.left <= lon <= b.right and b.bottom <= lat <= b.top):
            return None
        r, c = ds.index(lon, lat)
        vals = ds.read(window=Window(c, r, 1, 1))[:, 0, 0]
        nd = ds.nodata
    values = {k: (None if (nd is not None and v == nd) or not np.isfinite(v) else float(v))
              for k, v in zip(COMPONENTS, vals)}
    return contributions(values, rec.get("weights") or WEIGHTS)
