"""Which came first: heat and greenery over the seasonal history.

A single snapshot cannot tell whether vegetation cools the ground or heat dries out vegetation:
both give "greener = cooler". The seasonal history (same season, year to year) adds time order:

1. Heat first, greenery after ("heat may be stressing plants"):
   for each same-season pair of years (e.g. pre-monsoon 2024 -> pre-monsoon 2025), compare areas
   that START with similar greenery (ten equal-count NDVI bins, so a bare area is never compared
   with a forest) and ask: did the areas that were hotter at the start lose more greenery than the
   others in their bin by the next year? Changes are taken relative to the city-wide change of that
   pair, so a dry or wet year affecting everyone cancels out.
2. Greenery change and heat change together ("greening goes with cooling"):
   across the same pairs, do areas whose greenery rose (relative to the city) also cool (relative
   to the city)?

City-level results are Spearman rho values (effect sizes only: neighbouring areas are not
independent). For one area, the latest pair is checked against the same rules. Even with time
order these are associations, not proof of cause: rainfall, irrigation, construction or tree
cutting can drive both. Missing seasons (cloud) stay missing; nothing is filled in.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np
from scipy.stats import spearmanr
from sqlalchemy import text

N_BINS = 10
MIN_CELLS = 200
HOT_PCT = 80.0            # "hotter at the start" = among the hottest 20% of areas that season
MIN_NDVI_DROP = 0.03      # a greenery loss must also be physically visible
MIN_LST_DROP = 0.5        # °C, for "cooled"
CACHE_S = 3600.0
_CACHE: dict[str, dict[str, Any]] = {}     # per city: {"t": ..., "data": ...}


def _load(db=None) -> dict[str, Any] | None:
    from app.core.cities import current_city_id
    from app.services.history.analytics import _seasons, comparable

    city = current_city_id()
    hit = _CACHE.get(city)
    if hit and hit["data"] is not None and time.time() - hit["t"] < CACHE_S:
        return hit["data"]

    def run(d):
        seasons = _seasons(d)
        rows = d.execute(text("SELECT cell_id, season, ndvi, lst, ndmi_veg, openwater_frac FROM cell_history "
                              "WHERE city = :city"), {"city": city}).mappings().all()
        return seasons, rows

    if db is not None:
        seasons, rows = run(db)
    else:
        from app.database import SessionLocal
        with SessionLocal() as d:
            seasons, rows = run(d)
    if not seasons or not rows:
        return None
    by_key = {s["season"]: s for s in seasons}
    vals: dict[str, dict[int, dict]] = {}
    for r in rows:
        vals.setdefault(r["season"], {})[r["cell_id"]] = dict(r)
    pairs = []
    for s in seasons:
        prev = comparable(s, by_key)
        if prev and s["season"] in vals and prev["season"] in vals:
            p = _pair(vals[prev["season"]], vals[s["season"]])
            if p is not None:
                p.update(start=prev["label"], end=s["label"], start_key=prev["season"], end_key=s["season"])
                pairs.append(p)
    data = {"pairs": pairs}
    _CACHE[city] = {"t": time.time(), "data": data}
    return data


def _pair(a: dict[int, dict], b: dict[int, dict]) -> dict[str, Any] | None:
    """Per-area values for one start -> end pair, for land areas with NDVI and LST at both ends."""
    ids, rows = [], []
    for c, ra in a.items():
        rb = b.get(c)
        if not rb or (ra.get("openwater_frac") or 0) >= 0.5:
            continue
        v = (ra.get("ndvi"), ra.get("lst"), rb.get("ndvi"), rb.get("lst"), ra.get("ndmi_veg"), rb.get("ndmi_veg"))
        if any(x is None for x in v[:4]):
            continue
        ids.append(c)
        rows.append([float(x) if x is not None else np.nan for x in v])
    if len(ids) < MIN_CELLS:
        return None
    m = np.array(rows, dtype=float)
    ndvi0, lst0, ndvi1, lst1, ndmi0, ndmi1 = m.T
    d_ndvi = ndvi1 - ndvi0
    d_lst = lst1 - lst0
    d_ndmi = ndmi1 - ndmi0
    d_ndvi_rel = d_ndvi - np.median(d_ndvi)          # relative to the whole city's change
    d_lst_rel = d_lst - np.median(d_lst)
    ok_ndmi = np.isfinite(d_ndmi)
    d_ndmi_rel = np.where(ok_ndmi, d_ndmi - (np.median(d_ndmi[ok_ndmi]) if ok_ndmi.any() else 0.0), np.nan)
    heat_pct = (np.argsort(np.argsort(lst0)) + 0.5) / len(lst0) * 100.0
    edges = np.unique(np.quantile(ndvi0, np.linspace(0, 1, N_BINS + 1)))
    bin_ = np.clip(np.searchsorted(edges, ndvi0, side="right") - 1, 0, len(edges) - 2)
    return {"ids": np.array(ids), "ndvi0": ndvi0, "lst0": lst0, "heat_pct": heat_pct, "bin": bin_,
            "d_ndvi": d_ndvi, "d_ndvi_rel": d_ndvi_rel, "d_lst": d_lst, "d_lst_rel": d_lst_rel,
            "d_ndmi_rel": d_ndmi_rel}


def _within_bin_rho(p: dict, x: np.ndarray, y: np.ndarray) -> tuple[float, int] | None:
    rs, ws = [], []
    for b in np.unique(p["bin"]):
        m = p["bin"] == b
        if m.sum() >= 30 and np.std(x[m]) > 0 and np.std(y[m]) > 0:
            rs.append(float(spearmanr(x[m], y[m])[0]))
            ws.append(int(m.sum()))
    if not rs:
        return None
    return float(np.average(rs, weights=ws)), int(sum(ws))


def _strength(rho: float) -> str:
    a = abs(rho)
    return "strong" if a >= 0.5 else "moderate" if a >= 0.3 else "weak" if a >= 0.1 else "negligible"


PATTERN_WORD = {"strong": "Strong pattern", "moderate": "Clear pattern", "weak": "Weak pattern",
                "negligible": "No real pattern"}


def city_patterns(data: dict) -> dict[str, Any]:
    """Both time-ordered patterns over every same-season pair in the history."""
    heat, cool = [], []
    for p in data["pairs"]:
        h = _within_bin_rho(p, p["heat_pct"], p["d_ndvi_rel"])
        if h:
            heat.append(h)
        if np.std(p["d_ndvi_rel"]) > 0 and np.std(p["d_lst_rel"]) > 0:
            cool.append((float(spearmanr(p["d_ndvi_rel"], p["d_lst_rel"])[0]), len(p["ids"])))
    out: dict[str, Any] = {"pairs": [f"{p['start']} → {p['end']}" for p in data["pairs"]]}
    if heat:
        rho = float(np.average([r for r, _ in heat], weights=[n for _, n in heat]))
        s = _strength(rho)
        out["heat_then_greenery"] = {
            "rho": round(rho, 2), "n": int(sum(n for _, n in heat)), "year_pairs": len(heat), "strength": s,
            "pattern": PATTERN_WORD[s],
            "headline": ("Hotter areas went on to lose more greenery the next year" if rho < 0 and s != "negligible"
                         else "Hotter areas did not lose more greenery than similar areas" if s == "negligible"
                         else "Hotter areas went on to gain more greenery the next year"),
            "method": ("Areas compared only with areas of similar starting greenery (10 NDVI groups); "
                       "greenery change measured relative to the whole city's change for each pair of years."),
        }
    if cool:
        rho = float(np.average([r for r, _ in cool], weights=[n for _, n in cool]))
        s = _strength(rho)
        out["greening_cooling"] = {
            "rho": round(rho, 2), "n": int(sum(n for _, n in cool)), "year_pairs": len(cool), "strength": s,
            "pattern": PATTERN_WORD[s],
            "headline": ("Where greenery grew, the ground usually cooled" if rho < 0 and s != "negligible"
                         else "Greenery change and ground heat change were hardly linked" if s == "negligible"
                         else "Where greenery grew, the ground usually warmed"),
            "method": "Changes of greenery and of ground heat between the same season in two years, each relative "
                      "to the whole city's change.",
        }
    return out


def area_time_order(cell_id: int, db=None) -> dict[str, Any] | None:
    """The city patterns plus what happened in this area over the latest pair of years."""
    try:
        data = _load(db)
    except Exception:
        return None
    if not data or not data["pairs"]:
        return None
    city = city_patterns(data)
    out = {"city": city, "here": None}

    def supported(key: str) -> bool:
        """An area is only described by a pattern the whole city actually shows (in the expected
        direction). Without it a single area's change could be anything, so nothing is said."""
        c = city.get(key)
        return bool(c) and c["rho"] < 0 and c["strength"] != "negligible"

    for p in reversed(data["pairs"]):           # latest pair that contains this area
        idx = np.where(p["ids"] == cell_id)[0]
        if not len(idx):
            continue
        i = int(idx[0])
        same_bin = p["bin"] == p["bin"][i]
        q25 = float(np.quantile(p["d_ndvi_rel"][same_bin], 0.25))
        q75 = float(np.quantile(p["d_ndvi_rel"][same_bin], 0.75))
        l25 = float(np.quantile(p["d_lst_rel"][same_bin], 0.25))
        hot = p["heat_pct"][i] >= HOT_PCT
        lost = p["d_ndvi_rel"][i] <= q25 and p["d_ndvi"][i] <= -MIN_NDVI_DROP
        gained = p["d_ndvi_rel"][i] >= q75
        cooled = p["d_lst_rel"][i] <= l25 and p["d_lst"][i] <= -MIN_LST_DROP
        dry = np.isfinite(p["d_ndmi_rel"][i]) and p["d_ndmi_rel"][i] < 0
        here = {"start": p["start"], "end": p["end"],
                "hot_at_start": bool(hot), "heat_percentile_at_start": round(float(p["heat_pct"][i])),
                "lst_start_c": round(float(p["lst0"][i]), 1),
                "ndvi_start": round(float(p["ndvi0"][i]), 2), "ndvi_change": round(float(p["d_ndvi"][i]), 3),
                "ndvi_change_vs_city": round(float(p["d_ndvi_rel"][i]), 3),
                "lst_change_vs_city": round(float(p["d_lst_rel"][i]), 1),
                "moisture_fell": bool(dry), "signals": []}
        if hot and lost and supported("heat_then_greenery"):
            here["signals"].append({
                "id": "heat_stress_vegetation", "label": "Heat may be stressing the plants",
                "plain": (f"In {p['start']} this area was among the hottest 20% ({p['lst0'][i]:.1f} °C). By {p['end']} "
                          f"its greenery had dropped by {abs(p['d_ndvi'][i]):.2f} NDVI, more than most areas that "
                          f"started equally green" + ("; its plants also hold less water now (NDMI fell)." if dry else ".")),
            })
        if gained and cooled and supported("greening_cooling"):
            here["signals"].append({
                "id": "greening_cooling", "label": "Greener and cooler than before",
                "plain": (f"Between {p['start']} and {p['end']} this area's greenery grew more than in most similar areas, "
                          f"and its ground cooled by {abs(p['d_lst_rel'][i]):.1f} °C compared with the city."),
            })
        out["here"] = here
        break
    return out
