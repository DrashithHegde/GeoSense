"""How the layers relate to each other, and where one 300 m area sits on those relationships.

For each pair of layers (e.g. vegetation and surface heat) we use every 300 m area in the study
region (the ML feature snapshot) to get:

* the city-wide pattern: Spearman's rho (monotonic association) and n — effect size only, no
  p-value, because neighbouring areas are not independent;
* what is TYPICAL for areas like this one: the areas are grouped into ten equal-count bins of the
  first layer, and for this area's bin we take the median and middle half (25th-75th percentile)
  of the second layer.

This area is then "about typical", "higher than typical" or "lower than typical" for its
neighbours-in-kind — e.g. "warmer than typical for its vegetation". It is a comparison with
similar areas, not a cause. AQI pairs carry a caution: between stations AQI is interpolated,
so its effective sample size is the number of stations, and no per-area comparison is made.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np
from scipy.stats import spearmanr
from sqlalchemy import text

MIN_N = 60
N_BINS = 10
_CACHE: dict[str, dict[str, Any]] = {}     # per city: {"t": ..., "rows": ...}
CACHE_S = 3600.0

# feature names in the ML snapshot · key in the area values · display
LAYER = {
    "ndvi_land_mean": {"area": "ndvi", "name": "vegetation", "more": "more vegetation",
                       "label": "Vegetation (NDVI)", "fmt": "{:.2f}"},
    "built_frac": {"area": None, "name": "built-up share", "more": "a larger built-up share",
                   "label": "Built-up share", "fmt": "{:.0%}"},
    "lst_mean": {"area": "lst_c", "name": "surface temperature", "more": "hotter surfaces",
                 "label": "Surface heat (LST)", "fmt": "{:.1f} °C"},
    "aqi_idw": {"area": "aqi", "name": "AQI", "more": "higher AQI", "label": "Air quality (AQI)", "fmt": "{:.0f}"},
    "wh_mean": {"area": "water_health", "name": "Water Health", "more": "better Water Health",
                "label": "Water Health", "fmt": "{:.3f}"},
}
# (x, y, scope, words for y higher / lower than typical, layers this pair belongs to)
PAIRS = [
    ("ndvi_land_mean", "lst_mean", "land", ("warmer", "cooler"), ("ndvi", "lst")),
    ("built_frac", "lst_mean", "land", ("warmer", "cooler"), ("lst",)),
    ("ndvi_land_mean", "aqi_idw", "land", None, ("ndvi", "aqi")),
    ("lst_mean", "aqi_idw", "land", None, ("lst", "aqi")),
    # areas with water: city-wide link only (an area's LST is mostly its land, so a per-area
    # "typical for its Water Health" comparison would not mean much)
    ("wh_mean", "lst_mean", "water", None, ("water_health", "lst")),
]


# Plain-language pattern per pair, by direction (rho < 0 / rho > 0)
PLAIN = {
    ("ndvi_land_mean", "lst_mean"): ("Greener areas are usually cooler", "Greener areas are usually warmer"),
    ("built_frac", "lst_mean"): ("More built-up areas are usually cooler", "More built-up areas are usually hotter"),
    ("ndvi_land_mean", "aqi_idw"): ("Greener areas usually have cleaner air", "Greener areas usually have more polluted air"),
    ("lst_mean", "aqi_idw"): ("Hotter areas usually have cleaner air", "Hotter areas usually have more polluted air"),
    ("wh_mean", "lst_mean"): ("Healthier water usually sits in cooler areas", "Healthier water usually sits in warmer areas"),
}
SHORT = {"ndvi_land_mean": "greenery", "built_frac": "buildings and bare ground", "lst_mean": "ground heat",
         "aqi_idw": "air pollution", "wh_mean": "water health"}
SIMILAR = {"ndvi_land_mean": "similar greenery", "built_frac": "a similar share of buildings and bare ground",
           "lst_mean": "similar ground heat", "wh_mean": "similar water health"}
PATTERN_WORD = {"strong": "Strong pattern", "moderate": "Clear pattern", "weak": "Weak pattern",
                "negligible": "No real pattern"}


def _strength(rho: float) -> str:
    a = abs(rho)
    return "strong" if a >= 0.6 else "moderate" if a >= 0.4 else "weak" if a >= 0.2 else "negligible"


def _rows() -> list[dict]:
    """Every area's snapshot features in the current city (cached for an hour)."""
    from app.core.cities import current_city_id
    city = current_city_id()
    hit = _CACHE.get(city)
    if hit and hit["rows"] is not None and time.time() - hit["t"] < CACHE_S:
        return hit["rows"]
    from app.database import SessionLocal
    with SessionLocal() as db:
        # latest snapshot per area (older snapshots of the same area would count twice)
        res = db.execute(text("""
            SELECT DISTINCT ON (ef.cell_id) ef.feature_values -> 'raw_values' AS f
            FROM engineered_features ef JOIN spatial_cells sc ON sc.id = ef.cell_id
            WHERE sc.city = :city
            ORDER BY ef.cell_id, ef.observed_at DESC, ef.id DESC
        """), {"city": city}).fetchall()
    # only the columns the pairs use (a full feature row per area would hold tens of MB per city)
    keep = {k for x, y, *_ in PAIRS for k in (x, y)} | {"openwater_frac"}
    rows = [{k: r[0].get(k) for k in keep} for r in res if r[0]]
    _CACHE[city] = {"t": time.time(), "rows": rows}
    return rows


def _fmt(feature: str, v: float) -> str:
    return LAYER[feature]["fmt"].format(v)


def _pair(rows: list[dict], x: str, y: str, scope: str) -> dict | None:
    base = [r for r in rows if (r.get("openwater_frac") or 0) < 0.5] if scope == "land" else \
        [r for r in rows if r.get("wh_mean") is not None]
    a = np.array([[r.get(x), r.get(y)] for r in base if r.get(x) is not None and r.get(y) is not None],
                 dtype=float).reshape(-1, 2)
    a = a[np.isfinite(a).all(axis=1)]
    if len(a) < MIN_N or np.std(a[:, 0]) == 0 or np.std(a[:, 1]) == 0:
        return None
    rho = float(spearmanr(a[:, 0], a[:, 1])[0])
    edges = np.unique(np.quantile(a[:, 0], np.linspace(0, 1, N_BINS + 1)))
    return {"xy": a, "rho": rho, "n": int(len(a)), "edges": edges}


def _typical(p: dict, xv: float) -> dict | None:
    a, edges = p["xy"], p["edges"]
    i = int(np.clip(np.searchsorted(edges, xv, side="right") - 1, 0, len(edges) - 2))
    lo, hi = edges[i], edges[i + 1]
    m = (a[:, 0] >= lo) & (a[:, 0] <= hi)
    ys = a[m, 1]
    if len(ys) < 10:
        return None
    q25, med, q75 = (float(v) for v in np.quantile(ys, [0.25, 0.5, 0.75]))
    return {"x_range": [float(lo), float(hi)], "median": med, "q25": q25, "q75": q75, "n": int(len(ys))}


def area_relationships(ev: dict, focus: str | None = None, n_stations: int | None = None) -> list[dict[str, Any]]:
    """The relationships for this area's tab (all of them on Composite)."""
    try:
        rows = _rows()
    except Exception:          # no database: the section is simply left out
        return []
    area = ev.get("area") or {}
    feats = (ev.get("cell") or {}).get("features") or {}
    out = []
    for x, y, scope, words, layers in PAIRS:
        if focus and focus != "composite" and focus not in layers:
            continue
        p = _pair(rows, x, y, scope)
        if p is None:
            continue
        rho, strength = p["rho"], _strength(p["rho"])
        xn, yn = LAYER[x]["name"], LAYER[y]["name"]
        if strength == "negligible":
            city = f"Across the study region there is no clear link between {xn} and {yn} (ρ = {rho:+.2f}, {p['n']:,} areas)."
        else:
            city = (f"Across the study region, areas with {LAYER[x]['more']} tend to have "
                    f"{'higher' if rho > 0 else 'lower'} {yn} ({strength} link, ρ = {rho:+.2f}, {p['n']:,} areas).")
        neg, pos = PLAIN.get((x, y), (city, city))
        headline = (f"{SHORT[x].capitalize()} and {SHORT[y]} are hardly linked in this city"
                    if strength == "negligible" else (pos if rho > 0 else neg))
        item: dict[str, Any] = {
            "id": f"{x}__{y}", "x": x, "y": y, "title": f"{LAYER[x]['label']} ↔ {LAYER[y]['label']}",
            # for everyone: the pattern in plain words, how reliable it is, and what it means here
            "headline": headline, "pattern": PATTERN_WORD[strength],
            "rho": round(rho, 2), "n": p["n"], "strength": strength,
            "direction": "positive" if rho > 0 else "negative", "city_text": city, "here": None,
        }
        if "aqi_idw" in (x, y):
            stations = f"{n_stations} stations" if n_stations else "a limited number of stations"
            item["caution"] = (f"AQI between stations is interpolated from {stations}, so it changes "
                               "over kilometres, not 300 m; this link is indicative only and is not judged per area.")
            item["caution_plain"] = (f"Air quality is measured at {stations} only, so this is a city-wide "
                                     "pattern and is not judged for this one area.")
        else:
            xv = area.get(LAYER[x]["area"]) if LAYER[x]["area"] else feats.get(x)
            yv = area.get(LAYER[y]["area"])
            t = _typical(p, float(xv)) if xv is not None else None
            if t is not None and yv is not None and words:
                hi_w, lo_w = words
                verdict = (f"{hi_w} than typical" if yv > t["q75"] else f"{lo_w} than typical" if yv < t["q25"]
                           else "about typical")
                diff = yv - t["median"]
                unit_y = " °C" if y == "lst_mean" else ""
                if verdict == "about typical":
                    plain = f"This area is about as {'warm' if y == 'lst_mean' else 'high'} as other places with {SIMILAR[x]}."
                else:
                    plain = (f"This area is {abs(diff):.1f}{unit_y} {hi_w if diff > 0 else lo_w} than other places "
                             f"with {SIMILAR[x]}.") if y == "lst_mean" else \
                            (f"This area is {verdict.replace(' than typical', '')} than other places with {SIMILAR[x]}.")
                item["here"] = {
                    "x": xv, "y": yv, "typical": round(t["median"], 3), "range": [round(t["q25"], 3), round(t["q75"], 3)],
                    "verdict": verdict, "similar_areas": t["n"], "plain": plain,
                    "label": ("As expected" if verdict == "about typical" else
                              f"{hi_w.capitalize()} than expected" if diff > 0 else f"{lo_w.capitalize()} than expected"),
                    "y_text": _fmt(y, yv), "typical_text": _fmt(y, t["median"]),
                    "range_text": [_fmt(y, t["q25"]), _fmt(y, t["q75"])],
                    "text": (f"Areas with similar {xn} ({_fmt(x, t['x_range'][0])}–{_fmt(x, t['x_range'][1])}) are typically "
                             f"{_fmt(y, t['median'])} (middle half {_fmt(y, t['q25'])}–{_fmt(y, t['q75'])}); this area is "
                             f"{_fmt(y, yv)}, {verdict} for its {xn}."),
                }
        # say nothing about pairs that are not really linked: no pattern, or a weak one this area
        # does not stand out on (an AQI pair has no per-area check, so it needs a clear pattern)
        here = item.get("here")
        if strength == "negligible":
            continue
        if strength == "weak" and not (here and here["verdict"] != "about typical"):
            continue
        out.append(item)
    return out
