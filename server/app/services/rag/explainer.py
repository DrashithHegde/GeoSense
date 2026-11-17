"""Point explanation engine: evidence -> signals -> RAG -> (optional LLM) -> validated answer.

Layers, in order of authority:
  1. EVIDENCE   exact pixel values + 300 m cell features + persisted model outputs
  2. SIGNALS    deterministic rules over the evidence (always produced)
  3. KNOWLEDGE  BM25 retrieval from the cited knowledge base
  4. LLM        optional rewrite into plain language; rejected if it introduces
                numbers not in the evidence/knowledge, cites unknown sources or
                uses causal language. Deterministic text is the fallback.
"""
from __future__ import annotations
from app.core.cities import city_path, get_city

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from app.services.qc import lst_qc_min_c
from app.services.rag import retriever
from app.services.rag.guardrails import AnswerOut, SummaryOut, check_question, parse_output, sanitize_passages
from app.services.rag.llm import LLMUnavailable, active_provider, complete_json

ML_SUMMARY = city_path("ml", "ml_summary.json")
CAUSAL = ("caused by", "because of", "is due to", "responsible for", "results from", "leads to")
# Satellite proxies and interpolated AQI cannot certify quality or safety.
OVERCLAIM = ("good water quality", "water quality is good", "water is clean", "clean water", "safe water",
             "safe to drink", "drinkable", "safe to swim", "polluted water", "water is polluted", "contaminated",
             "water quality is poor", "poor water quality", "air is clean", "clean air", "air is safe",
             "safe to breathe", "healthy air", "no pollution", "pollution-free")


@lru_cache(maxsize=8)
def _summary_cached(path: str, mtime: float) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def ml_summary() -> dict:
    """The current city's ML summary (cached per file and modification time)."""
    p = ML_SUMMARY.resolve_path()
    if not p.exists():
        return {}
    return _summary_cached(str(p), p.stat().st_mtime)


def _ckb(role: str) -> list[str]:
    """The current city's knowledge note for a role (e.g. its air-pollution sources), if it has one."""
    kid = get_city().kb.get(role)
    return [kid] if kid else []


def city_percentile(feature: str, value: float | None) -> float | None:
    table = (ml_summary().get("city_percentiles") or {}).get(feature)
    if value is None or not table:
        return None
    return round(float(np.interp(value, table, np.arange(101))), 0)


def _r(v, d=3):
    return None if v is None else round(float(v), d)


def _fmt_driver(d: dict) -> str:
    v, f = d.get("value"), d.get("feature", "")
    if v is None:
        shown = "n/a"
    elif f.endswith("_frac"):
        shown = f"{v * 100:.0f}%"
    elif f == "dist_water_m":
        shown = f"{v:.0f} m"
    else:
        shown = f"{v:.2f}"
    return f"{d['label']} {shown} ({d['effect_c']:+.1f} °C)"


def ndvi_band(v: float | None) -> str | None:
    if v is None:
        return None
    if v < 0:
        return "open water / wet surface"
    if v < 0.2:
        return "bare or built-up surface"
    if v < 0.4:
        return "sparse vegetation"
    if v < 0.6:
        return "moderate vegetation"
    return "dense vegetation"


# ─────────────────────────────────────────────────────────────────────────────
# 1. Evidence
# ─────────────────────────────────────────────────────────────────────────────

def build_evidence(analysis: dict) -> dict[str, Any]:
    pixel = analysis.get("pixel") or {}
    cell = analysis.get("cell") or {}
    muni = (analysis.get("municipality") or {}).get("name") or cell.get("municipality_name_from_cell")
    feats = cell.get("features") or {}
    models = cell.get("models") or {}

    def pv(key, field="value"):
        b = pixel.get(key) or {}
        return None if b.get("nodata", True) else b.get(field)

    ndvi_px = pv("ndvi")
    lst_px = pv("lst", "value_c")
    lst_qc = (pixel.get("lst") or {}).get("qc_flag")
    if lst_qc:
        lst_px = None
    aqi_b = pixel.get("aqi") or {}

    cell_feats = {k: _r(feats.get(k), 3) for k in ("ndvi_mean", "veg_frac", "built_frac", "openwater_frac",
                                                   "water_frac", "lst_mean", "lst_std", "wh_mean", "dist_water_m", "aqi_idw",
                                                   "ndmi_veg_mean", "ndbi_land_mean", "composite_cell", "composite_coverage",
                                                   "comp_heat", "comp_surface", "comp_air")}
    if cell_feats.get("dist_water_m") is not None:
        cell_feats["dist_water_m"] = round(cell_feats["dist_water_m"])
    pct = {k: city_percentile(k, feats.get(k)) for k in ("ndvi_mean", "built_frac", "veg_frac", "lst_mean", "wh_mean",
                                                         "ndmi_veg_mean", "ndbi_land_mean", "composite_cell", "composite_coverage",
                                                   "comp_heat", "comp_surface", "comp_air")}

    iso = (models.get("isolation_forest_cell_v2") or {}).get("evidence") or {}
    xgb = (models.get("xgboost_lst_residual_v1") or {}).get("evidence") or {}
    whz = (models.get("water_health_robust_z_v1") or {}).get("evidence") or {}

    layers = {}
    for layer in ("ndvi", "lst", "water_health", "aqi"):
        e = (models.get(f"isolation_forest_{layer}_v1") or {}).get("evidence") or {}
        if e:
            layers[layer] = {"is_anomaly": e.get("is_anomaly"), "direction": e.get("direction"),
                             "score_percentile": _r(e.get("score_percentile"), 0), "value": _r(e.get("value"), 3),
                             "dominant_deviations": (e.get("dominant_deviations") or [])[:3]}
    station_if = None
    near = (aqi_b.get("nearest_station") or {}).get("station_name") if aqi_b.get("available") else None
    if near:
        for st in (ml_summary().get("station_isolation_forest") or {}).get("stations") or []:
            if st.get("station_name") == near:
                station_if = {k: st.get(k) for k in ("station_name", "is_anomaly", "score_percentile",
                                                     "dominant_deviations", "aqi")}
                break

    gaps = []
    if ndvi_px is None:
        gaps.append("No valid NDVI pixel at this exact point.")
    if (pixel.get("lst") or {}).get("nodata", True):
        gaps.append("No cloud-free Landsat LST pixel at this point in the current composite.")
    elif lst_qc:
        gaps.append(f"LST pixel below {lst_qc_min_c():.0f} °C flagged as probable residual cloud and not interpreted.")
    if not aqi_b.get("available"):
        gaps.append("AQI unavailable: " + (aqi_b.get("reason") or "no fresh station coverage").rstrip(".") + ".")
    if not models:
        gaps.append("No ML results stored for this cell yet (run scripts/run_ml_pipeline.py).")

    point = {
        "ndvi": _r(ndvi_px), "ndvi_band": ndvi_band(ndvi_px),
        "lst_c": _r(lst_px, 1),
        "water_health": _r(pv("water_health")),
        "aqi": aqi_b.get("value") if aqi_b.get("available") else None,
        "aqi_category": (aqi_b.get("category") or {}).get("name") if aqi_b.get("available") else None,
        "aqi_nearest_station": aqi_b.get("nearest_station") if aqi_b.get("available") else None,
        "aqi_reliability": aqi_b.get("reliability") if aqi_b.get("available") else None,
        "composite_stress": _r(pv("composite")),
        "composite_breakdown": (pixel.get("composite") or {}).get("breakdown"),
        "ndmi": _r(pv("ndmi")),
        "ndbi": _r(pv("ndbi")),
    }
    area = _area_values(cell.get("metrics") or {}, point)
    if area["basis"].get("lst") == "area" and point["lst_c"] is None:
        gaps.append("The exact 30 m point has no valid Landsat LST (cloud gap); the 300 m area average is used.")

    return {
        "location": analysis.get("location"),
        "municipality": muni,
        "place_label": (analysis.get("place") or {}).get("label") or muni,
        "cell_code": cell.get("cell_code"),
        # what the analysis is about: the 300 m area around the click (values computed from the
        # current map layers); "point" = the exact clicked pixel, shown as a side note only
        "area": area,
        "point": point,
        # seasonal history in time order: heat first / greenery after, greening with cooling
        "time_order": _time_order(cell.get("id")),
        "cell": {"features": cell_feats, "city_percentiles": pct},
        "history": cell.get("history"),
        "models": {
            "isolation_forest": None if not iso else {
                "is_anomaly": iso.get("is_anomaly"), "score_percentile": _r(iso.get("score_percentile"), 0),
                "dominant_deviations": iso.get("dominant_deviations"),
            },
            "xgboost_lst": None if not xgb else {
                "observed_lst_c": xgb.get("observed_lst_c"), "expected_lst_c": xgb.get("expected_lst_c"),
                "residual_c": xgb.get("residual_c"), "flag": xgb.get("flag"), "top_drivers": xgb.get("top_drivers"),
                "cv_r2": _r((xgb.get("cv_metrics") or {}).get("r2_spatial_cv"), 2),
                "cv_rmse_c": _r((xgb.get("cv_metrics") or {}).get("rmse_c"), 1),
            },
            "water_health": None if not whz else {
                "wh_mean": whz.get("wh_mean"), "robust_z": whz.get("robust_z"),
                "percentile": whz.get("percentile"), "flag": whz.get("flag"),
            },
            "layer_isolation_forest": layers or None,
            "station_isolation_forest": station_if,
        },
        "data_gaps": gaps,
        "sources": cell.get("feature_sources"),
    }


def _time_order(cell_id) -> dict | None:
    if cell_id is None:
        return None
    try:
        from app.services.history.time_order import area_time_order
        return area_time_order(int(cell_id))
    except Exception:
        return None


def _area_values(metrics: dict, point: dict) -> dict[str, Any]:
    """The 300 m area's values (live cell means of the current map layers); for any value the area
    does not have, the exact point's value, recorded in basis[...] = "point"."""
    from app.services.surfaces.aqi_station_surface import cpcb_category
    basis: dict[str, str] = {}

    def pick(key, area_v, point_v, nd=3):
        if area_v is not None:
            basis[key] = "area"
            return _r(area_v, nd)
        if point_v is not None:
            basis[key] = "point"
        return point_v

    ndvi_area = metrics.get("ndvi_land") if metrics.get("ndvi_land") is not None else metrics.get("ndvi")
    ndvi = pick("ndvi", ndvi_area, point["ndvi"])
    aqi = pick("aqi", metrics.get("aqi"), point["aqi"], 0)
    aqi = int(aqi) if aqi is not None else None
    comp = metrics.get("composite_breakdown")
    out = {
        "ndvi": ndvi, "ndvi_band": ndvi_band(ndvi),
        "lst_c": pick("lst", metrics.get("lst"), point["lst_c"], 1),
        "water_health": pick("water_health", metrics.get("water_health_score"), point["water_health"]),
        "aqi": aqi,
        "aqi_category": ((cpcb_category(aqi) or {}).get("name") if basis.get("aqi") == "area"
                         else point["aqi_category"]) if aqi is not None else None,
        "aqi_nearest_station": point["aqi_nearest_station"],
        "aqi_reliability": point["aqi_reliability"],
        "composite_stress": comp["score"] if comp else point["composite_stress"],
        "composite_breakdown": comp if comp else point["composite_breakdown"],
        "ndmi": point["ndmi"], "ndbi": point["ndbi"],
    }
    basis["composite"] = "area" if comp else ("point" if point["composite_breakdown"] else "none")
    out["basis"] = basis
    return out


# What each supporting measurement is, how it is computed, and which cited note explains it.
SUB = {
    "ndvi": ("Greenness (NDVI)", "(B8 − B4) / (B8 + B4) from Sentinel-2, 10 m; land pixels only", "ndvi_ranges", "ndvi_mean"),
    "ndmi": ("Plant moisture (NDMI)", "(B8 − B11) / (B8 + B11) from Sentinel-2, 20 m; vegetated pixels only", "ndmi_moisture",
             "ndmi_veg_mean"),
    "veg_frac": ("Dense vegetation share", "share of the area with NDVI ≥ 0.5", "ndvi_ranges", "veg_frac"),
    "built_frac": ("Built-up / bare share", "share of the area with NDVI 0–0.2", "ndbi_builtup", "built_frac"),
    "ndbi": ("Built-up index (NDBI)", "(B11 − B8) / (B11 + B8) from Sentinel-2 (= −NDMI); land pixels", "ndbi_builtup",
             "ndbi_land_mean"),
    "lst": ("Ground surface temperature (LST)", "Landsat 8/9 surface-temperature band, °C; 30 m (measured at 100 m)",
            "landsat_lst", "lst_mean"),
    "dist_water": ("Distance to open water", "mean distance from the area's pixels to the nearest water (NDVI < 0)",
                   "vegetation_cooling", None),
    "wh": ("Water Health", "0–1 from a chlorophyll proxy (NDCI, B5/B4) and a turbidity proxy (B3/B4) on water pixels",
           "water_health_geosense", "wh_mean"),
    "water_frac": ("Water share", "share of the area detected as water (MNDWI ≥ 0.15)", "mndwi", None),
}
SUB_FOR = {"ndvi": ["ndvi", "ndmi", "veg_frac", "built_frac", "ndbi"],
           "lst": ["lst", "built_frac", "ndbi", "veg_frac", "ndmi", "dist_water"],
           "water_health": ["wh", "water_frac", "dist_water"],
           "composite": ["lst", "ndvi", "ndmi", "built_frac", "wh"],
           "aqi": []}


def _meaning(key: str, v: float, p: float | None) -> str:
    if p is None:
        return ""
    hi, lo = p >= 80, p <= 20
    words = {
        "ndvi": ("greener than {p}% of areas", "less green than {q}% of areas"),
        "ndmi": ("plants hold more water than in {p}% of green areas", "plants are drier than in {q}% of green areas"),
        "veg_frac": ("more dense vegetation than {p}% of areas", "less dense vegetation than {q}% of areas"),
        "built_frac": ("more built-up or bare than {p}% of areas", "less built-up than {q}% of areas"),
        "ndbi": ("more built-up or bare than {p}% of areas", "less built-up than {q}% of areas"),
        "lst": ("hotter than {p}% of areas", "cooler than {q}% of areas"),
        "wh": ("healthier water than {p}% of water areas", "poorer water condition than {q}% of water areas"),
    }.get(key)
    if not words:
        return ""
    if hi:
        return words[0].format(p=round(p), q=round(100 - p))
    if lo:
        return words[1].format(p=round(p), q=round(100 - p))
    return "typical for the city (percentile %d)" % round(p)


def supporting_measures(ev: dict, focus: str | None) -> list[dict[str, Any]]:
    """The sub-layers behind this tab's main value: value, what it means here (vs the city),
    how it is computed, and the cited note that explains it."""
    a, cf, pct = ev.get("area") or {}, ev["cell"]["features"], ev["cell"]["city_percentiles"]
    values = {"ndvi": a.get("ndvi"), "ndmi": cf.get("ndmi_veg_mean"), "veg_frac": cf.get("veg_frac"),
              "built_frac": cf.get("built_frac"), "ndbi": cf.get("ndbi_land_mean"), "lst": a.get("lst_c"),
              "dist_water": cf.get("dist_water_m"), "wh": a.get("water_health"),
              "water_frac": cf.get("water_frac") if cf.get("water_frac") is not None else cf.get("openwater_frac")}
    out = []
    for key in SUB_FOR.get(focus or "composite", SUB_FOR["composite"]):
        v = values.get(key)
        if v is None:
            continue
        name, how, kb, pkey = SUB[key]
        p = city_percentile(pkey, v) if pkey else None
        if p is None and pkey:
            p = pct.get(pkey)
        fmt = (f"{v * 100:.0f}%" if key in ("veg_frac", "built_frac", "water_frac") else f"{v:.1f} °C" if key == "lst"
               else f"{v:.0f} m" if key == "dist_water" else f"{v:.3f}" if key == "wh" else f"{v:.2f}")
        note = retriever.get(kb) or {}
        out.append({"key": key, "name": name, "value": round(float(v), 4), "display": fmt,
                    "percentile": None if p is None else round(float(p)), "meaning": _meaning(key, v, p),
                    "how": how, "kb": kb, "source": note.get("source"), "url": note.get("url"),
                    "source_title": note.get("title")})
    if focus in ("aqi", "composite"):
        st = a.get("aqi_nearest_station") or {}
        names = {"pm25": "PM2.5", "pm10": "PM10", "no2": "NO₂", "so2": "SO₂", "o3": "O₃", "co": "CO", "nh3": "NH₃"}
        note = retriever.get("aqi_cpcb_scale") or {}
        for k, v in sorted((st.get("sub_indices") or {}).items(), key=lambda kv: -(kv[1] or 0)):
            if v is None or (focus == "composite" and k != st.get("dominant_pollutant")):
                continue
            out.append({"key": f"aqi_{k}", "name": f"{names.get(k, k)} sub-index ({st.get('station_name')})",
                        "value": v, "display": f"{v:g}",
                        "meaning": ("decides the AQI here (highest sub-index)" if k == st.get("dominant_pollutant") else ""),
                        "how": "CPCB 2014 breakpoints on the station's 24 h average (8 h for O₃ and CO)",
                        "kb": "aqi_cpcb_scale", "source": note.get("source"), "url": note.get("url"),
                        "source_title": note.get("title"), "percentile": None})
    return out


def _where(ev: dict, key: str) -> str:
    """'across this 300 m area' or 'at the clicked point', by where the value came from."""
    return "at the clicked point" if (ev.get("area") or {}).get("basis", {}).get(key) == "point" \
        else "across this 300 m area"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Deterministic signals + recommendations
# ─────────────────────────────────────────────────────────────────────────────

def _green_cool_sentence() -> str:
    from app.services.ml.relationships import headline
    h = headline(ml_summary().get("relationships"), "ndvi_mean", "lst_mean")
    if h and h["spearman_rho"] < 0:
        return (f"Across the region greener cells are usually cooler (NDVI vs LST Spearman rho {h['spearman_rho']:+.2f}, "
                f"{h['n']} cells), so this location breaks the usual pattern and needs a closer look.")
    return "Greener places are usually cooler, so this needs a closer look."


COMPONENT_NAMES = {"heat": "heat", "surface": "surface condition", "air": "air"}
HISTORY_PREFIX = {"lst": "heat_history", "ndvi": "vegetation_history", "ndmi_veg": "vegetation_moisture_history",
                  "wh": "water_history", "ndbi_land": "heat_builtup_history"}
# which direction of change is a concern (for the signal level)
WORSE_IF = {"lst": "up", "ndvi": "down", "ndmi_veg": "down", "wh": "down", "ndbi_land": "up"}


def _fmt_delta(m: str, d: float, unit: str) -> str:
    return f"{d:+.1f} {unit}".strip() if m == "lst" else f"{d:+.2f}"


NOTABLE_LOCAL_CHANGE = {"lst": 1.0, "ndvi": 0.05, "ndmi_veg": 0.05, "wh": 0.03, "ndbi_land": 0.05}


def _history_signals(h: dict | None) -> list[dict]:
    """Seasonal history: same-season change, sudden change, persistence, trend, station AQI."""
    if not h:
        return []
    out = []
    for m, e in (h.get("metrics") or {}).items():
        pre = HISTORY_PREFIX.get(m)
        if not pre:
            continue
        ch = e.get("change")
        reg0 = (ch or {}).get("region_median_delta")
        local = None if not ch else ch["delta"] - (reg0 or 0.0)
        # mention a change only when it stands out: sudden, or clearly different from the city's
        # own change over the same seasons (a change the whole city shared says nothing about here)
        if ch and not ch["sudden"] and abs(local) < NOTABLE_LOCAL_CHANGE.get(m, 1e9):
            ch = None
        if ch:
            worse = (ch["delta"] > 0) == (WORSE_IF[m] == "up")
            reg = ch.get("region_median_delta")
            if ch["sudden"]:
                tail = ("a sudden change: far larger than the change in almost all cells over the same seasons"
                        + (f" (region median {_fmt_delta(m, reg, e['unit'])})" if reg is not None else ""))
                lvl = "warning" if worse else "notice"
            else:
                tail = (f"{_fmt_delta(m, local, e['unit'])} compared with the change across the city"
                        + (f" (city median {_fmt_delta(m, reg, e['unit'])})" if reg is not None else ""))
                lvl = "info"
            out.append({"id": f"{pre}_change", "level": lvl, "kb": ["history_method"],
                        "text": f"{e['label']} here changed {_fmt_delta(m, ch['delta'], e['unit'])} from {ch['from']} "
                                f"to {ch['to']} — {tail}."})
        ps = e.get("persistence")
        if ps and ps["seasons_flagged"] >= 2:
            out.append({"id": f"{pre}_persistent", "level": "notice" if ps["persistent"] else "info",
                        "kb": ["history_method"],
                        "text": f"In the {ps['description']} of cells in {ps['seasons_flagged']} of "
                                f"{ps['seasons_observed']} seasons observed since 2023"
                                + (" — a persistent pattern, not a one-off." if ps["persistent"] else ".")})
        for kind, t in (e.get("trend") or {}).items():
            if abs(t["per_year"]) * (t["seasons"] - 1) >= {"lst": 1.0, "ndvi": 0.05, "ndmi_veg": 0.05, "wh": 0.03,
                                                           "ndbi_land": 0.05}[m]:
                name = (get_city().seasons.get(kind) or (None, None, kind))[2].lower()
                out.append({"id": f"{pre}_trend", "level": "info", "kb": ["history_method"],
                            "text": f"Over {t['seasons']} {name} seasons, {e['label']} here has moved "
                                    f"{_fmt_delta(m, t['per_year'], e['unit'])} per year (Theil-Sen; indicative with "
                                    "so few seasons)."})
    ci = h.get("change_isolation_forest")
    if ci and ci.get("is_anomaly"):
        names = {"d_lst": "LST", "d_ndvi": "NDVI", "d_ndmi_veg": "vegetation moisture"}
        top = sorted(ci["z"].items(), key=lambda kv: -abs(kv[1]))[:2]
        out.append({"id": "history_change_outlier", "level": "notice", "kb": ["isolation_forest", "history_method"],
                    "text": "The combination of changes since the comparable season last year is unusual for the "
                            "region (change-aware Isolation Forest): " + ", ".join(
                                f"{names.get(k, k)} change {ci['changes'][k]:+.2f} ({v:+.1f}σ)" for k, v in top) + "."})
    st = h.get("station") or {}
    if st.get("change"):
        c = st["change"]
        cur = next((x["aqi_median"] for x in st["series"] if x["label"] == c["to"]), None)
        out.append({"id": "aqi_history_change", "level": "info", "kb": ["history_method", "aqi_cpcb_scale"],
                    "text": f"At the nearest station ({st['station_name']}), the median daily CPCB AQI in {c['to']} was "
                            + (f"{cur:.0f}, " if cur is not None else "")
                            + f"{c['delta']:+.0f} compared with {c['from']} (24-hour pollutants only)."})
    return out


def _composite_signals(px: dict, cf: dict, pct: dict) -> list[dict]:
    """Composite v2: the score and what it is made of, for the 300 m area (else the point / ML snapshot)."""
    out = []
    b = px.get("composite_breakdown")
    where = "this 300 m area" if (px.get("basis") or {}).get("composite") == "area" else "the clicked point"
    if not b and cf.get("composite_cell") is not None:
        from app.services.composite_v2 import WEIGHTS, contributions
        b = contributions({k: cf.get(f"comp_{k}") for k in ("heat", "surface", "air")}, WEIGHTS)
        where = "this 300 m area"
    if not b:
        return out
    p = pct.get("composite_cell")
    if not b.get("components"):     # an older composite without per-part values: the score only
        out.append({"id": "composite_breakdown", "level": "notice" if (p or 0) >= 85 else "info", "kb": ["composite_method"],
                    "text": f"Composite stress for {where} is {b['score']:.2f} on a 0-1 scale"
                            + (f" (percentile {p:.0f} among 300 m areas)." if p is not None else ".")})
        return out
    parts = sorted(b["components"].items(), key=lambda kv: -kv[1]["points"])
    shares = ", ".join(f"{COMPONENT_NAMES[k]} {v['share_pct']:.0f}%" for k, v in parts)
    miss = ", ".join(COMPONENT_NAMES[k] for k in b["missing"])
    p = pct.get("composite_cell")
    level = "notice" if (p or 0) >= 85 else "info"
    out.append({"id": "composite_breakdown", "level": level, "kb": ["composite_method"],
                "text": f"Composite stress for {where} is {b['score']:.2f} on a 0-1 scale"
                        + (f" (percentile {p:.0f} among 300 m areas)" if p is not None else "")
                        + f", from {b['coverage']} components: {shares} of the score"
                        + (f"; {miss} not available here, so the weights were renormalised." if miss else ".")})
    return out


def derive_signals(ev: dict) -> list[dict[str, Any]]:
    S: list[dict[str, Any]] = []
    px, cf, pct, m = ev["area"], ev["cell"]["features"], ev["cell"]["city_percentiles"], ev["models"]

    if px["ndvi"] is not None:
        on_land = ev["area"]["basis"].get("ndvi") == "area"
        S.append({"id": "vegetation_area", "level": "info", "kb": ["ndvi_ranges"],
                  "text": f"Vegetation {_where(ev, 'ndvi')}: NDVI {px['ndvi']:.2f} ({px['ndvi_band']})"
                          + (" (land only; water excluded)." if on_land else ".")})
    if cf.get("built_frac") is not None and pct.get("built_frac") is not None:
        if pct["built_frac"] >= 75:
            S.append({"id": "built_up", "level": "notice", "kb": ["uhi", *_ckb("ndvi_season")],
                      "text": f"{cf['built_frac']*100:.0f}% of this 300 m cell is bare/built-up surface "
                              f"(higher than {pct['built_frac']:.0f}% of cells in the study region)."})
        elif cf.get("veg_frac") is not None and (pct.get("veg_frac") or 0) >= 75:
            S.append({"id": "green_cell", "level": "info", "kb": ["vegetation_cooling"],
                      "text": f"{cf['veg_frac']*100:.0f}% of this cell is dense vegetation "
                              f"(greener than {pct['veg_frac']:.0f}% of cells)."})

    # vegetation moisture (NDMI of the cell's vegetated 20 m pixels) — "green but dry" check
    nm, nmp = cf.get("ndmi_veg_mean"), pct.get("ndmi_veg_mean")
    if nm is not None and nmp is not None:
        if nmp <= 20:
            S.append({"id": "vegetation_dry", "level": "notice", "kb": ["ndmi_moisture"],
                      "text": f"The vegetation in this cell is drier than in most vegetated cells: moisture index "
                              f"(NDMI) {nm:.2f}, percentile {nmp:.0f}."})
        elif nmp >= 80:
            S.append({"id": "vegetation_moist", "level": "info", "kb": ["ndmi_moisture"],
                      "text": f"The vegetation in this cell is moister than in most vegetated cells: moisture index "
                              f"(NDMI) {nm:.2f}, percentile {nmp:.0f}."})

    lst_v = px["lst_c"]
    # percentile of the area's current LST among all 300 m areas (falls back to the ML snapshot's)
    lst_p = city_percentile("lst_mean", lst_v) if lst_v is not None else None
    if lst_p is None and lst_v is not None:
        lst_p = pct.get("lst_mean")
    if lst_v is not None and lst_p is not None:
        p = lst_p
        lvl = "warning" if p >= 85 else "notice" if p >= 70 else "info"
        word = ("among the hottest areas" if p >= 85 else "hotter than most areas" if p >= 70
                else "cooler than most areas" if p <= 30 else "typical for the study region")
        S.append({"id": "heat_cell", "level": lvl, "kb": ["landsat_lst", "lst_vs_air"],
                  "text": f"Land surface temperature {_where(ev, 'lst')} is {lst_v:.1f} °C — {word} "
                          f"(percentile {p:.0f})."})
    # cell-level test: the temperature is the cell mean, so the vegetation must be the cell's too
    # (a green pixel inside a built-up block is not "green cover")
    if (lst_p or 0) >= 70 and not _water_dominated(cf) and (
            (pct.get("veg_frac") or 0) >= 60 or (cf.get("ndvi_mean") or 0) >= 0.45) and \
            (pct.get("built_frac") or 0) < 75:
        S.append({"id": "heat_despite_green", "level": "notice", "kb": ["lst_vegetation_relationship", "ndmi_moisture"],
                  "text": f"Hot despite green cover: surface temperature is in percentile {lst_p:.0f} although "
                          "this location has substantial vegetation. " + _green_cool_sentence()})
    nb, nbp = cf.get("ndbi_land_mean"), pct.get("ndbi_land_mean")
    if nb is not None and nbp is not None and (nbp >= 80 or nbp <= 20):
        S.append({"id": "heat_builtup_index", "level": "info", "kb": ["ndbi_builtup"],
                  "text": f"The land in this cell is {'more' if nbp >= 80 else 'less'} built-up or bare than "
                          f"{nbp if nbp >= 80 else 100 - nbp:.0f}% of cells by the built-up index (NDBI {nb:.2f})."})

    x = m.get("xgboost_lst")
    if x and x.get("flag") in ("unexplained_heat", "unexplained_cooling"):
        drivers = ", ".join(_fmt_driver(d) for d in (x.get("top_drivers") or [])[:3])
        hot = x["flag"] == "unexplained_heat"
        S.append({"id": x["flag"], "level": "warning" if hot else "notice",
                  "kb": ["residual_interpretation", "xgboost_shap", "spatial_cv"],
                  "text": f"XGBoost expects {x['expected_lst_c']} °C from land cover but Landsat observed "
                          f"{x['observed_lst_c']} °C (residual {x['residual_c']:+.1f} °C, beyond 2× the model's "
                          f"{x['cv_rmse_c']} °C cross-validated error). Largest modelled contributions vs the city baseline: {drivers}."})
    elif x:
        drivers = ", ".join(_fmt_driver(d) for d in (x.get("top_drivers") or [])[:3])
        S.append({"id": "heat_explained", "level": "info", "kb": ["xgboost_shap"],
                  "text": f"Observed LST is consistent with land cover (expected {x['expected_lst_c']} °C, "
                          f"residual {x['residual_c']:+.1f} °C). Largest modelled contributions vs the city baseline: {drivers}."})

    S.extend(_composite_signals(px, cf, pct))
    S.extend(_history_signals(ev.get("history")))
    for sig in ((ev.get("time_order") or {}).get("here") or {}).get("signals") or []:
        S.append({"id": sig["id"], "level": "notice" if sig["id"] == "heat_stress_vegetation" else "info",
                  "kb": ["heat_stress_vegetation", "ndmi_moisture"] if sig["id"] == "heat_stress_vegetation"
                  else ["vegetation_cooling"], "text": sig["plain"]})

    i = m.get("isolation_forest")
    if i and i.get("is_anomaly"):
        devs = i.get("dominant_deviations") or []
        dev = "; ".join(f"{d['label']} {d['direction']} normal ({d['z']:+.1f}σ)" for d in devs[:2])
        water_driven = bool(devs) and devs[0]["feature"] in ("openwater_frac", "water_frac")
        # + means "worse" for these features, - means "worse" for the greenery ones
        worse_if_high = {"built_land_frac", "built_frac", "lst_mean", "aqi_idw", "lst_std"}
        worse_if_low = {"ndvi_land_mean", "ndvi_mean", "veg_land_frac", "veg_frac"}
        top = [d for d in devs[:2] if abs(d.get("z") or 0) >= 1]
        favourable = bool(top) and all(
            (d["feature"] in worse_if_high and d["z"] < 0) or (d["feature"] in worse_if_low and d["z"] > 0) for d in top)
        S.append({"id": "multivariate_outlier_water" if water_driven else
                        "multivariate_outlier_favourable" if favourable else "multivariate_outlier",
                  "level": "notice" if (water_driven or favourable) else "warning", "kb": ["isolation_forest"],
                  "text": f"Isolation Forest flags this cell as a multivariate outlier (score higher than "
                          f"{i['score_percentile']:.0f}% of cells): {dev}."
                          + (" This mainly reflects that water-dominated cells are rare in the city, not a hazard by itself."
                             if water_driven else
                             " It is unusual in a favourable direction (greener / cooler / less built-up than typical)."
                             if favourable else "")})

    if px["ndvi"] is None and cf.get("ndvi_mean") is None:
        S.append({"id": "vegetation_unavailable", "level": "info", "kb": ["cloud_gaps"],
                  "text": "No valid Sentinel-2 NDVI for this cell in the current composite (cloud or outside coverage)."})
    if cf.get("lst_mean") is None and px["lst_c"] is None:
        S.append({"id": "heat_unavailable", "level": "info", "kb": ["cloud_gaps", "landsat_lst"],
                  "text": "No cloud-free Landsat surface temperature for this cell in the current composite, so the "
                          "heat models were not run here (nothing is filled in)."})
    if px["water_health"] is None and cf.get("wh_mean") is None:
        S.append({"id": "water_not_applicable", "level": "info", "kb": ["water_health_geosense", "mndwi"],
                  "text": "No water detected in this cell (MNDWI), so Water Health does not apply here — it is "
                          "computed only for water pixels."})

    LAYER_NAMES = {"ndvi": "vegetation (NDVI)", "lst": "surface temperature (LST)",
                   "water_health": "Water Health", "aqi": "AQI"}
    BAD = {"ndvi": "low", "lst": "high", "water_health": "low", "aqi": "high"}
    for layer, L in (m.get("layer_isolation_forest") or {}).items():
        if not L.get("is_anomaly"):
            continue
        word = {"high": "unusually high", "low": "unusually low", "pattern": "an unusual pattern"}.get(L.get("direction"), "unusual")
        devs = "; ".join(f"{d['label']} {d['z']:+.1f}σ" for d in (L.get("dominant_deviations") or [])[:2])
        S.append({"id": f"layer_{layer}_outlier", "level": "warning" if L.get("direction") == BAD[layer] else "notice",
                  "kb": ["layer_isolation_forest"],
                  "text": f"Isolation Forest for the {LAYER_NAMES[layer]} layer flags this cell as {word} "
                          f"(score higher than {L['score_percentile']:.0f}% of cells): {devs}."})

    wh_v = px["water_health"] if px["water_health"] is not None else cf.get("wh_mean")
    if wh_v is not None:
        wp = city_percentile("wh_mean", wh_v)
        here = "This 300 m area contains water" if ev["area"]["basis"].get("water_health") != "point" \
            else "Water detected at the clicked point"
        S.append({"id": "water_pixel" if (wp is None or wp > 20) else "water_pixel_low",
                  "level": "info" if (wp is None or wp > 20) else "notice",
                  "kb": ["water_health_geosense", "mndwi", "ndci"],
                  "text": f"{here}; its Water Health index averages {wh_v:.3f}"
                          + (f" (percentile {wp:.0f} among water areas)." if wp is not None else ".")})
    w = m.get("water_health")
    if w and w.get("flag") == "low_water_condition":
        S.append({"id": "water_low", "level": "warning", "kb": ["water_health_geosense", "turbidity_proxy", "water_quality_insitu"],
                  "text": f"This cell's water bodies score {w['wh_mean']:.3f}, {abs(w['robust_z']):.1f} robust-σ below "
                          f"the median water cell — an optical stress signal (algal/turbidity proxies), not a lab result."})

    if px["aqi"] is not None:
        lvl = "warning" if px["aqi"] > 200 else "notice" if px["aqi"] > 100 else "info"
        st = px.get("aqi_nearest_station") or {}
        S.append({"id": "aqi", "level": lvl, "kb": ["aqi_cpcb_scale", "aqi_health_statements", "idw_method"],
                  "text": f"AQI {_where(ev, 'aqi')} is {px['aqi']} ({px['aqi_category']}, CPCB scale); nearest "
                          f"station {st.get('station_name')} is {st.get('distance_m')} m away."})
    rel = px.get("aqi_reliability")
    if px["aqi"] is not None and rel:
        err = (f"; at held-out stations the estimate was typically within ±{rel['typical_error_aqi']:.0f} AQI points"
               if rel.get("typical_error_aqi") is not None else "")
        S.append({"id": "aqi_reliability", "level": "info", "kb": ["idw_method", "aqi_loso_validation"],
                  "text": f"Reliability of this interpolated value: {rel['label']} (nearest station "
                          f"{rel['nearest_station_m']} m away, {rel['stations_within_10km']} station(s) within 10 km{err})."})
    if px["aqi"] is None:
        gap = next((g for g in ev.get("data_gaps", []) if g.startswith("AQI unavailable")), None)
        S.append({"id": "aqi_unavailable", "level": "info", "kb": ["openaq_caaqms", "idw_method"],
                  "text": gap or "AQI is not available here (no fresh station coverage within range)."})
    st = px.get("aqi_nearest_station") or {}
    if px["aqi"] is not None and st.get("dominant_pollutant"):
        names = {"pm25": "PM2.5", "pm10": "PM10", "no2": "NO₂", "so2": "SO₂", "o3": "O₃", "co": "CO", "nh3": "NH₃"}
        subs = {names.get(k, k): v for k, v in (st.get("sub_indices") or {}).items() if v is not None}
        detail = ", ".join(f"{k} {v:g}" for k, v in sorted(subs.items(), key=lambda kv: -kv[1]))
        S.append({"id": "aqi_station_mix", "level": "info", "kb": ["aqi_cpcb_scale", *_ckb("air_sources")],
                  "text": f"At the nearest station ({st.get('station_name')}) the dominant pollutant is "
                          f"{names.get(st['dominant_pollutant'], st['dominant_pollutant'])} (station AQI {st.get('aqi')})"
                          + (f"; CPCB sub-indices: {detail}." if detail else ".")})
    sif = m.get("station_isolation_forest")
    if sif and sif.get("is_anomaly"):
        devs = "; ".join(f"{d['pollutant']} sub-index {d['sub_index']} ({d['z']:+.1f}σ)"
                         for d in (sif.get("dominant_deviations") or [])[:2])
        S.append({"id": "station_outlier", "level": "notice", "kb": ["station_isolation_forest", *_ckb("air_sources")],
                  "text": f"The nearest station ({sif['station_name']}) has an unusual pollutant mix compared with the "
                          f"other stations (station Isolation Forest): {devs}."})
    return S


FOCUS_SIGNALS = {
    "ndvi": ("vegetation", "built_up", "green_cell", "layer_ndvi", "history_change_outlier", "heat_stress_vegetation",
             "greening_cooling"),
    "lst": ("heat_cell", "heat_builtup_index", "unexplained_", "heat_explained", "heat_unavailable",
            "heat_stress_vegetation", "greening_cooling",
            "layer_lst", "heat_despite_green", "heat_history", "heat_builtup_history", "history_change_outlier"),
    "water_health": ("water_", "layer_water_health"),
    "aqi": ("aqi", "layer_aqi", "station_outlier"),  # includes aqi_station_mix
    "composite": ("composite_", "multivariate_outlier", "history_change_outlier"),
}


def focus_order(signals: list[dict], focus: str | None) -> list[dict]:
    """Put the signals for the layer being viewed first; keep everything else after."""
    keys = FOCUS_SIGNALS.get(focus or "", ())
    if not keys:
        return signals
    rel = [x for x in signals if any(x["id"].startswith(k) for k in keys)]
    return rel + [x for x in signals if x not in rel]


RECOMMENDATIONS = {
    "heat": ("mitigate_heat", "Prioritise cool/reflective roofs, street-tree shade and lighter permeable paving in this block; "
                              "protect any remaining open green or water space."),
    "green": ("mitigate_greening", "Protect existing tree and mangrove cover; add street trees or dense native plantations on open plots."),
    "water": ("mitigate_water", "Check for sewage outfalls, dumping or hyacinth growth and request sampling by the state "
                                "pollution control board or the municipality (DO, BOD, coliforms) to confirm the satellite signal."),
    "air": ("mitigate_air", "On Moderate-or-worse days limit prolonged outdoor exertion for sensitive groups; local dust "
                            "control and stopping waste burning reduce PM."),
    "inspect": ("isolation_forest", "The combination of values here is unusual for the region (see the deviations above). Check the "
                                    "block on recent imagery or on site before acting — the flag says where to look, not why."),
    "keep": ("mitigate_greening", "This location is environmentally favourable relative to the city; the main action is to "
                                  "protect its vegetation and water from conversion."),
}


# on a layer's tab only that layer's advice is given (heat advice never appears on the AQI tab)
REC_THEMES_FOR_FOCUS = {"lst": {"heat", "keep"}, "ndvi": {"green", "keep"}, "water_health": {"water"}, "aqi": {"air"}}


def recommendations(signals: list[dict], focus: str | None = None) -> list[dict]:
    ids = {s["id"] for s in signals}
    out = []
    bad = {s["id"] for s in signals if s["id"].startswith("layer_") and s["level"] == "warning"}
    if ids & {"unexplained_heat"} or "layer_lst_outlier" in bad or any(s["id"] == "heat_cell" and s["level"] != "info" for s in signals):
        out.append("heat")
    if "built_up" in ids or "layer_ndvi_outlier" in bad:
        out.append("green")
    if ids & {"water_low", "water_pixel_low"} or "layer_water_health_outlier" in bad:
        out.append("water")
    if "layer_aqi_outlier" in bad or any(s["id"] == "aqi" and s["level"] != "info" for s in signals):
        out.append("air")
    flagged = any(s["level"] == "warning" for s in signals)
    if not out and flagged:
        out.append("inspect")
    if not out and ("green_cell" in ids or "multivariate_outlier_favourable" in ids
                    or any(s["id"] == "heat_cell" and "cooler" in s["text"] for s in signals)):
        out.append("keep")
    if focus in REC_THEMES_FOR_FOCUS:
        out = [k for k in out if k in REC_THEMES_FOR_FOCUS[focus]]
    return [{"kb": RECOMMENDATIONS[k][0], "text": RECOMMENDATIONS[k][1], "theme": k} for k in out]


def classification(signals: list[dict]) -> str:
    if any(s["level"] == "warning" for s in signals):
        return "anomaly" if any(s["id"] in ("multivariate_outlier", "unexplained_heat", "water_low")
                                or (s["id"].startswith("layer_") and s["level"] == "warning") for s in signals) else "elevated"
    return "notice" if any(s["level"] == "notice" for s in signals) else "inlier"


POLLUTANT_NAMES = {"pm25": "PM2.5", "pm10": "PM10", "no2": "NO₂", "so2": "SO₂", "o3": "O₃", "co": "CO", "nh3": "NH₃"}
POLLUTANT_ASSOC = {
    "no2": "traffic and other fuel combustion",
    "pm10": "road and construction dust and re-suspended particles",
    "pm25": "combustion sources such as vehicles, industry and open waste burning",
    "so2": "industrial and fuel-oil combustion",
    "o3": "a secondary pollutant formed in sunlight from NOx and VOC emissions",
    "co": "incomplete combustion",
    "nh3": "sewage, waste decomposition, fertiliser and some industry",
}
FACTOR_THEME_FOR_FOCUS = {"lst": "heat", "ndvi": "veg", "water_health": "water", "aqi": "air"}


def _share(v) -> str:
    return "n/a" if v is None else f"{v * 100:.0f}%"


def _water_dominated(cf: dict) -> bool:
    """Most of the 300 m cell is open water (creek, lake, sea)."""
    return (cf.get("openwater_frac") or 0) >= 0.5


def _land_veg_frac(cf: dict) -> float | None:
    """Dense-vegetation share of the cell's LAND (water excluded); None if the cell is almost all water."""
    land = 1 - (cf.get("openwater_frac") or 0)
    if cf.get("veg_frac") is None or land < 0.2:
        return None
    return min(1.0, cf["veg_frac"] / land)


def associated_factors(ev: dict, signals: list[dict], focus: str | None = None) -> list[dict]:
    """Rule-based "possible associated factors" built only from this cell's evidence and
    cited knowledge. Always phrased as associations; never a cause."""
    F: list[dict] = []
    m, cf, pct, px = ev["models"], ev["cell"]["features"], ev["cell"]["city_percentiles"], ev["area"]
    ids = {s["id"] for s in signals}

    x = m.get("xgboost_lst")
    if x and x.get("flag") == "unexplained_heat":
        F.append({"theme": "heat", "kb": "residual_interpretation",
                  "text": f"Land cover explains about {x['expected_lst_c']} °C here but Landsat observed {x['observed_lst_c']} °C. "
                          f"The extra {x['residual_c']:+.1f} °C is not accounted for by built-up, vegetation or water share; "
                          "things the model cannot see (roof materials, industrial heat, paving) or a data artefact may be involved."})
    elif x and x.get("flag") == "unexplained_cooling":
        F.append({"theme": "heat", "kb": "residual_interpretation",
                  "text": f"The surface is {abs(x['residual_c']):.1f} °C cooler than its land cover suggests ({x['observed_lst_c']} vs "
                          f"{x['expected_lst_c']} °C); shade, irrigation, reflective roofs, nearby water or residual cloud may be involved."})
    elif x and x.get("top_drivers"):
        d = max(x["top_drivers"], key=lambda t: abs(t.get("effect_c") or 0))
        F.append({"theme": "heat", "kb": "xgboost_shap",
                  "text": f"In the temperature model, {_fmt_driver(d)} is the largest contribution relative to the city "
                          "baseline — a model attribution, not proof of cause."})
    if (pct.get("built_frac") or 0) >= 75 and (pct.get("lst_mean") or 0) >= 70:
        F.append({"theme": "heat", "kb": "uhi",
                  "text": f"A high built-up share ({_share(cf.get('built_frac'))} of the cell) with little vegetation is consistent "
                          "with the surface urban heat island: impervious, low-albedo surfaces heat up more than vegetated ground."})

    if "heat_despite_green" in ids:
        dry = "vegetation_dry" in ids
        F.append({"theme": "heat", "kb": "lst_vegetation_relationship",
                  "text": "Green but hot can have several explanations: the canopy may be too sparse or "
                          + ("dry (its moisture index is low here)" if dry else "dry to cool much")
                          + ", heat from surrounding built-up land, or the Sentinel-2 and Landsat composites "
                          "covering different dates. A canopy-density check or a same-date thermal image would tell "
                          "them apart; the satellite data alone cannot."})
    if (pct.get("ndbi_land_mean") or 0) >= 80 and (pct.get("lst_mean") or 0) >= 60:
        F.append({"theme": "heat", "kb": "ndbi_builtup",
                  "text": f"A high built-up index (NDBI {cf.get('ndbi_land_mean'):.2f}) is typically associated with warmer "
                          "surfaces; note that bare soil raises NDBI too, so it does not prove buildings."})
    if "vegetation_dry" in ids:
        F.append({"theme": "veg", "kb": "ndmi_moisture",
                  "text": "Low vegetation moisture (NDMI) with green cover is associated with water-stressed, sparse or "
                          "dry-season vegetation, which cools less through evapotranspiration."})

    ndvi_dir = ((m.get("layer_isolation_forest") or {}).get("ndvi") or {})
    ndvi_low_flag = bool(ndvi_dir.get("is_anomaly")) and ndvi_dir.get("direction") == "low"
    water_dom = _water_dominated(cf)
    if ("built_up" in ids or ndvi_low_flag) and not water_dom:
        F.append({"theme": "veg", "kb": "ndvi_ranges",
                  "text": f"Low greenness here goes with a large bare/built-up share ({_share(cf.get('built_frac'))}) and a "
                          f"dense-vegetation share of {_share(cf.get('veg_frac'))}."})
    if "green_cell" in ids and (pct.get("lst_mean") or 100) <= 50:
        F.append({"theme": "veg", "kb": "vegetation_cooling",
                  "text": "Dense vegetation is associated with cooler surfaces through shade and evapotranspiration, which is "
                          "consistent with this cell's lower surface temperature."})

    w = m.get("water_health")
    if (w and w.get("flag") == "low_water_condition") or "water_pixel_low" in ids or \
            (m.get("layer_isolation_forest") or {}).get("water_health", {}).get("direction") == "low":
        F.append({"theme": "water", "kb": "turbidity_proxy",
                  "text": "A low Water Health index is consistent with optical signs of algae (NDCI) or suspended sediment "
                          "(turbidity). Possible contributors to check on the ground include outfalls, stagnant water and "
                          "dumping; only water sampling can confirm."})

    st = px.get("aqi_nearest_station") or {}
    dom = st.get("dominant_pollutant")
    if px.get("aqi") is not None and dom in POLLUTANT_ASSOC:
        F.append({"theme": "air", "kb": "pollutant_signatures",
                  "text": f"The nearest station's dominant pollutant is {POLLUTANT_NAMES[dom]}, which is typically associated "
                          f"with {POLLUTANT_ASSOC[dom]}."})
    if px.get("aqi") is not None and (st.get("distance_m") or 0) > 3000:
        F.append({"theme": "air", "kb": "idw_method",
                  "text": f"The nearest monitoring station is {st['distance_m']} m away, so the interpolated AQI here is less "
                          "certain than near a station."})
    sif = m.get("station_isolation_forest")
    if sif and sif.get("is_anomaly"):
        top = (sif.get("dominant_deviations") or [{}])[0]
        F.append({"theme": "air", "kb": "station_isolation_forest",
                  "text": f"{sif['station_name']} has an unusual pollutant mix compared with other stations (mainly "
                          f"{top.get('pollutant')}), which may point to a local source worth checking."})

    i = m.get("isolation_forest")
    if i and i.get("is_anomaly") and not any(s["id"] == "multivariate_outlier_water" for s in signals):
        devs = [d["label"] for d in (i.get("dominant_deviations") or [])[:2]]
        if devs:
            F.append({"theme": "general", "kb": "isolation_forest",
                      "text": f"The combined outlier flag comes mainly from {' and '.join(devs)}; it marks a rare combination "
                              "of conditions, not necessarily a problem."})

    # Context factors that keep each layer's explanation meaningful
    ow = cf.get("openwater_frac")
    if water_dom and cf.get("lst_mean") is not None and (pct.get("lst_mean") or 100) <= 50:
        F.insert(0 if not (x and x.get("flag") in ("unexplained_heat", "unexplained_cooling")) else len(F), {"theme": "heat", "kb": "water_cooling",
                  "text": f"Most of this cell is open water ({_share(ow)}); water surfaces stay cooler than built-up "
                          "ground, which is consistent with the lower surface temperature here."})
    has_ndvi = px.get("ndvi") is not None or cf.get("ndvi_mean") is not None
    if has_ndvi and not any(f["theme"] == "veg" for f in F):
        if water_dom:
            F.append({"theme": "veg", "kb": "ndvi_ranges",
                      "text": f"Most of this cell is open water ({_share(ow)}), so a low NDVI here reflects water, "
                              "not missing vegetation."})
        elif cf.get("veg_frac") is not None and cf.get("built_frac") is not None:
            F.append({"theme": "veg", "kb": "ndvi_ranges",
                      "text": f"NDVI here mainly reflects the cell's mix of dense vegetation ({_share(cf['veg_frac'])}) "
                              f"and bare/built-up surface ({_share(cf['built_frac'])})."})
    if cf.get("wh_mean") is not None and not any(f["theme"] == "water" for f in F):
        F.append({"theme": "water", "kb": "water_health_geosense",
                  "text": "Water Health combines the satellite water mask (MNDWI) with chlorophyll (NDCI) and turbidity "
                          "proxies; this cell's water shows "
                          + ("fewer optical signs of algae or sediment than most water cells"
                             if (pct.get("wh_mean") or 0) >= 80 else "optical signals within the usual range of water cells")
                          + ", and only sampling can confirm actual quality."})

    want = FACTOR_THEME_FOR_FOCUS.get(focus or "")
    if want:
        # a single-layer view only shows factors for that layer
        return [f for f in F if f["theme"] == want]
    # combined view: air factors only when air quality is a concern here
    air_concern = (px.get("aqi") or 0) > 100 or _layer_flagged(ev)["aqi"]
    F = [f for f in F if f["theme"] != "air" or air_concern]
    flagged = _layer_flagged(ev)
    key = {"heat": "lst", "veg": "ndvi", "water": "water", "air": "aqi"}
    F.sort(key=lambda f: not flagged.get(key.get(f["theme"], ""), False))
    return F


# ── Mitigation strategies per layer (wording follows the cited mitigation notes) ──
MITIGATION = {
    "lst": {"title": "Reduce surface heat", "items": [
        ("cool_roofs", "mitigate_heat", "Cool / reflective roofs (high-albedo coatings) on large built-up roofs."),
        ("shade_trees", "mitigate_heat", "Shade trees along streets and footpaths."),
        ("green_roofs", "mitigate_heat", "Green roofs and small pocket parks on available space."),
        ("paving", "mitigate_heat", "Lighter-coloured, permeable paving instead of dark asphalt and concrete."),
        ("keep_open", "mitigate_heat", "Protect nearby water bodies, wetlands and open space that keep the area cooler."),
        ("heat_warning", "mitigate_heat", "Heat early warnings and cooling access for vulnerable residents on hot days."),
    ]},
    "ndvi": {"title": "Protect and increase green cover", "items": [
        ("protect_green", "mitigate_greening", "Protect existing trees, forest patches and mangroves first — more effective than new planting."),
        ("street_trees", "mitigate_greening", "Street trees along roads and footpaths in built-up blocks."),
        ("native_planting", "mitigate_greening", "Native-species tree planting on open plots, watered and maintained until established."),
        ("campus", "mitigate_greening", "Greening of school, hospital and institutional campuses."),
        ("water_green", "mitigate_greening", "Water-sensitive greening (rain gardens, mulching, rainwater retention) so existing vegetation stays moist through the dry season."),
    ]},
    "water_health": {"title": "Improve the water body", "items": [
        ("sample", "water_quality_insitu", "Confirm on the ground first: sampling of DO, BOD and coliforms by the state "
                                           "pollution control board or the municipality."),
        ("sewage", "mitigate_water", "Intercept and treat sewage before it enters the water body."),
        ("dumping", "mitigate_water", "Stop solid-waste dumping and encroachment along the banks."),
        ("hyacinth", "mitigate_water", "Remove invasive water hyacinth where it covers the surface."),
        ("buffer", "mitigate_water", "Restore vegetated and mangrove buffers along the edges."),
    ]},
    "aqi": {"title": "Reduce air pollution and exposure", "items": [
        ("dust_sites", "mitigate_air", "Enforce construction-dust controls (barricades, covers, sprinkling) at building sites."),
        ("road_dust", "mitigate_air", "Mechanised road sweeping and water sprinkling; pave unpaved road shoulders."),
        ("burning", "mitigate_air", "Stop open waste burning and landfill fires."),
        ("traffic", "mitigate_air", "Cleaner / electric buses and fleets and smoother traffic on busy corridors."),
        ("industry", "mitigate_air", "Control industrial and fuel-oil emissions from nearby units."),
        ("exposure", "aqi_health_statements", "On Moderate-or-worse days, sensitive groups limit prolonged outdoor exertion."),
    ]},
}


# The specific evidence behind each measure (shown under the measure in Deep Analysis).
MEASURE_EVIDENCE = {
    "cool_roofs": ("Santamouris 2014, Solar Energy 103", "https://doi.org/10.1016/j.solener.2012.07.003"),
    "green_roofs": ("Santamouris 2014, Solar Energy 103", "https://doi.org/10.1016/j.solener.2012.07.003"),
    "paving": ("Santamouris 2013, Renew. Sustain. Energy Rev. 26", "https://doi.org/10.1016/j.rser.2013.05.047"),
    "shade_trees": ("Ziter et al. 2019, PNAS 116; Bowler et al. 2010", "https://doi.org/10.1073/pnas.1817561116"),
    "street_trees": ("Ziter et al. 2019, PNAS 116; Bowler et al. 2010", "https://doi.org/10.1073/pnas.1817561116"),
    "keep_open": ("Völker et al. 2013, Erdkunde 67; Bowler et al. 2010", "https://doi.org/10.1016/j.landurbplan.2010.05.006"),
    "heat_warning": ("NDMA 2019 heat-wave guidelines; Knowlton et al. 2014, IJERPH 11", "https://doi.org/10.3390/ijerph110403473"),
    "protect_green": ("Bowler et al. 2010, Landsc. Urban Plan. 97", "https://doi.org/10.1016/j.landurbplan.2010.05.006"),
    "native_planting": ("Bowler et al. 2010, Landsc. Urban Plan. 97", "https://doi.org/10.1016/j.landurbplan.2010.05.006"),
    "campus": ("Bowler et al. 2010, Landsc. Urban Plan. 97", "https://doi.org/10.1016/j.landurbplan.2010.05.006"),
    "water_green": ("Coutts et al. 2013, Prog. Phys. Geogr. 37", "https://doi.org/10.1177/0309133312461032"),
    "sample": ("CPCB National Water Quality Monitoring Programme", "https://cpcb.nic.in/"),
    "sewage": ("MoEFCC National Plan for Conservation of Aquatic Ecosystems", None),
    "dumping": ("MoEFCC Solid Waste Management Rules 2016", None),
    "hyacinth": ("Villamagna & Murphy 2010, Freshw. Biol. 55", "https://doi.org/10.1111/j.1365-2427.2009.02294.x"),
    "buffer": ("Mayer et al. 2007, J. Environ. Qual. 36; Barbier et al. 2011, Ecol. Monogr. 81", "https://doi.org/10.2134/jeq2006.0462"),
    "dust_sites": ("NCAP 2019; MoEFCC Construction and Demolition Waste Management Rules 2016", "https://moef.gov.in/"),
    "road_dust": ("NCAP 2019 city action plans", "https://moef.gov.in/"),
    "burning": ("MoEFCC Solid Waste Management Rules 2016; NCAP 2019", "https://moef.gov.in/"),
    "traffic": ("NCAP 2019 city action plans", "https://moef.gov.in/"),
    "industry": ("NCAP 2019; CPCB emission standards", "https://cpcb.nic.in/"),
    "exposure": ("CPCB National AQI 2014 health statements", "https://cpcb.nic.in/national-air-quality-index/"),
}


def mitigation_plan(ev: dict, signals: list[dict], focus: str | None = None, n: int = 4) -> dict:
    """Layer-specific mitigation strategies, with the ones that fit this cell's evidence first."""
    cf, pct, px, m = ev["cell"]["features"], ev["cell"]["city_percentiles"], ev["area"], ev["models"]
    ids = {s["id"] for s in signals}
    L = m.get("layer_isolation_forest") or {}
    water_dom = _water_dominated(cf)
    built_hi = (pct.get("built_frac") or 0) >= 70 and not water_dom
    lv = _land_veg_frac(cf)
    veg_lo = lv is not None and lv < 0.15
    lst_flag_hot = (L.get("lst") or {}).get("is_anomaly") and (L.get("lst") or {}).get("direction") == "high"
    hot = (pct.get("lst_mean") or 0) >= 70 or "unexplained_heat" in ids or bool(lst_flag_hot)
    ndvi_flag_low = (L.get("ndvi") or {}).get("is_anomaly") and (L.get("ndvi") or {}).get("direction") == "low"
    water_low = bool({"water_low", "water_pixel_low"} & ids) or \
        ((L.get("water_health") or {}).get("is_anomaly") and (L.get("water_health") or {}).get("direction") == "low")
    has_water = cf.get("wh_mean") is not None or px.get("water_health") is not None or (cf.get("openwater_frac") or 0) > 0.05
    has_wh = cf.get("wh_mean") is not None or px.get("water_health") is not None
    dom = (px.get("aqi_nearest_station") or {}).get("dominant_pollutant")
    aqi = px.get("aqi")
    aqi_concern = (aqi is not None and aqi > 100) or _layer_flagged(ev)["aqi"]
    green_hi = (pct.get("veg_frac") or 0) >= 60 and not water_dom
    # Is action on this layer a priority at this spot?
    priority = {"lst": hot, "ndvi": veg_lo or built_hi or bool(ndvi_flag_low) or "vegetation_dry" in ids,
                "water_health": bool(water_low),
                "aqi": aqi_concern}
    PROTECTIVE = {"keep_open", "protect_green", "buffer"}

    why = {
        "cool_roofs": built_hi and "large built-up share", "shade_trees": veg_lo and "very little tree cover",
        "heat_warning": hot and "among the hotter cells", "keep_open": has_water and "water nearby",
        "street_trees": built_hi and "large built-up share", "protect_green": green_hi and "existing dense greenery",
        "native_planting": veg_lo and "very little tree cover",
        "water_green": "vegetation_dry" in ids and "vegetation drier than most vegetated cells",
        "sample": water_low and "low Water Health signal", "sewage": water_low and "low Water Health signal",
        "dumping": water_low and "low Water Health signal",
        "buffer": has_wh and "water edges in this cell",
        "dust_sites": dom == "pm10" and "PM10 dominant at nearest station",
        "road_dust": dom == "pm10" and "PM10 dominant at nearest station",
        "burning": dom == "pm25" and "PM2.5 dominant at nearest station",
        "traffic": dom == "no2" and "NO₂ dominant at nearest station",
        "industry": dom == "so2" and "SO₂ dominant at nearest station",
        "exposure": aqi is not None and aqi > 100 and "AQI is Moderate or worse",
    }

    # Measures that make no physical sense for a mostly-water cell
    if water_dom:
        for key in ("cool_roofs", "green_roofs", "paving", "street_trees", "native_planting", "campus", "shade_trees"):
            why[key] = None

    def pick(layer: str, k: int, only: set | None = None) -> list[dict]:
        rows = []
        for key, kb, text in MITIGATION[layer]["items"]:
            if only is not None and key not in only:
                continue
            reason = why.get(key) or None
            # ★ only when the layer needs action here, or the measure protects what is already good
            star = bool(reason) and (priority[layer] or key in PROTECTIVE)
            cite, url = MEASURE_EVIDENCE.get(key, (None, None))
            rows.append({"key": key, "kb": kb, "text": text, "fits_this_cell": star,
                         "why": reason if star else None, "layer": layer, "_match": bool(reason),
                         "evidence": {"cite": cite, "url": url} if cite else None})
        rows.sort(key=lambda r: (not r["fits_this_cell"], not r["_match"]))  # stable: catalogue order kept
        for r in rows:
            r.pop("_match")
        return rows[:k]

    def plan(layer, items, note=None, applicable=True, title=None):
        return {"layer": layer, "title": title or MITIGATION[layer]["title"], "applicable": applicable,
                "priority": bool(priority.get(layer)), "note": note, "items": items}

    if focus in MITIGATION:
        # no measurement on this layer here -> no measures (nothing is suggested without evidence)
        if focus == "water_health" and not has_wh:
            return plan(focus, [], "No water detected in this cell, so water-body measures do not apply here.", False)
        if focus == "aqi" and aqi is None:
            return plan(focus, [], "AQI is unavailable here, so no air-quality measures are suggested.", False)
        if focus == "lst" and px.get("lst_c") is None and cf.get("lst_mean") is None:
            return plan(focus, [], "Surface temperature is unavailable here (no cloud-free Landsat pixels in the "
                                   "current composite), so no heat measures are suggested.", False)
        if focus == "ndvi" and px.get("ndvi") is None and cf.get("ndvi_mean") is None:
            return plan(focus, [], "Vegetation (NDVI) is unavailable here, so no greening measures are suggested.",
                        False)
        if focus == "lst" and water_dom:
            return plan(focus, pick("lst", 2, {"keep_open", "heat_warning"} if hot else {"keep_open"}),
                        f"This cell is mostly open water ({_share(cf.get('openwater_frac'))}), so building-level heat "
                        "measures (roofs, paving, street trees) do not apply; protecting the water body keeps the area cooler.")
        if focus == "ndvi" and water_dom:
            items = pick("ndvi", 1, {"protect_green"}) + pick("water_health", 1, {"buffer"})
            for it in items:
                it["fits_this_cell"], it["why"] = True, "mangrove and wetland edges"
            return plan(focus, items, f"This cell is mostly open water ({_share(cf.get('openwater_frac'))}), so "
                                      "tree-planting measures do not apply; protect the vegetated edges instead.")
        notes = {
            "lst": "Surface heat is not a priority here (not among the hotter cells and not flagged); "
                   "protective measures come first.",
            "ndvi": "Vegetation is not a priority here (not flagged as low); protecting existing green cover matters most.",
            "water_health": "Water Health is within the usual range for water cells, so these are routine measures; "
                            "confirm with sampling before acting.",
            "aqi": f"AQI is {px.get('aqi_category') or 'not elevated'} here and not flagged, so air measures are not "
                   "a priority" + (f"; those matching the nearest station's dominant pollutant "
                                   f"({POLLUTANT_NAMES.get(dom, dom)}) are listed first." if dom else "."),
        }
        return plan(focus, pick(focus, n), None if priority[focus] else notes[focus])

    # composite: the two most relevant measures from each layer that needs action here
    layers = [l for l in ("lst", "ndvi", "water_health", "aqi") if priority[l]]
    if water_dom:
        layers = [l for l in layers if l != "ndvi"]
    if layers:
        items = [r for l in layers for r in pick(l, 2)][:6]
        return plan("composite", items, title="Priority measures for this location")
    # nothing needs action: protect what keeps this place in good condition - but only when the
    # main layers were actually measured here (missing data is never read as "in good condition")
    if px.get("lst_c") is None or px.get("ndvi") is None:
        return plan("composite", [], "Not enough measured layers here to judge which measures would help.", False,
                    title="Measures for this location")
    items = []
    if has_water:
        items += pick("lst", 1, {"keep_open"})
    if green_hi or not water_dom:
        items += pick("ndvi", 1, {"protect_green"})
    if has_wh:
        items += pick("water_health", 1, {"buffer"})
    return {"layer": "composite", "title": "Protect what keeps this location in good condition", "applicable": True,
            "priority": False, "note": "No layer needs priority action here.", "items": items}


FOCUS_LABEL = {"ndvi": "NDVI / vegetation", "lst": "LST / surface heat", "water_health": "Water Health",
               "aqi": "CPCB AQI / air quality", "composite": "all layers combined"}


def deterministic_text(ev: dict, signals: list[dict], recs: list[dict], focus: str | None = None,
                       factors: list[dict] | None = None) -> dict[str, Any]:
    where = ev.get("place_label") or ev["municipality"] or "the study region"
    keys = FOCUS_SIGNALS.get(focus or "", ())
    pool = [s for s in signals if any(s["id"].startswith(k) for k in keys)] if keys else []
    pool = pool or signals
    warnings = [s for s in pool if s["level"] == "warning"]
    notices = [s for s in pool if s["level"] == "notice"]
    head = warnings[0]["text"] if warnings else notices[0]["text"] if notices else (
        pool[0]["text"] if pool else "No valid satellite observation at this point.")
    cls = classification(pool if keys and focus in FACTOR_THEME_FOR_FOCUS else signals)
    return {
        "headline": f"{where}: " + (["Flagged by GeoSense models", "Elevated signal", "Notable conditions", "No unusual signal"]
                                    [["anomaly", "elevated", "notice", "inlier"].index(cls)]),
        "summary": head,
        "what_we_see": [s["text"] for s in signals],
        "why_it_might_be": [f["text"] for f in (factors or [])],
        "what_could_help": [r["text"] for r in recs],
        "caveats": ev["data_gaps"] + ["Model signals are statistical associations within one satellite snapshot, not proof of cause."],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3/4. RAG + optional LLM with validation
# ─────────────────────────────────────────────────────────────────────────────

def _numbers(text: str) -> set[float]:
    # strip thousands separators first ("1,948 m" is one number, not 1 and 948)
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)
    return {float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", text)}


def any_model_flag(ev: dict | None) -> bool:
    m = (ev or {}).get("models") or {}
    if (m.get("isolation_forest") or {}).get("is_anomaly"):
        return True
    if (m.get("xgboost_lst") or {}).get("flag") in ("unexplained_heat", "unexplained_cooling"):
        return True
    if (m.get("water_health") or {}).get("flag") in ("low_water_condition", "high_water_condition"):
        return True
    if any((v or {}).get("is_anomaly") for v in (m.get("layer_isolation_forest") or {}).values()):
        return True
    return bool((m.get("station_isolation_forest") or {}).get("is_anomaly"))


def validate_llm(out: dict, allowed_text: str, allowed_ids: set[str], ev: dict | None = None) -> list[str]:
    problems = []
    body = json.dumps({k: v for k, v in out.items() if k != "citations"}, ensure_ascii=False)
    allowed = _numbers(allowed_text)
    for n in _numbers(body):
        if n in (0, 1, 2, 3) or any(abs(n - a) <= max(0.051, abs(a) * 0.005) for a in allowed):
            continue
        # percentages of fractions (0.62 -> 62%)
        if any(abs(n - a * 100) <= 0.6 for a in allowed if abs(a) <= 1):
            continue
        # metres restated as kilometres (1948 m -> 1.9 km)
        if any(abs(n * 1000 - a) <= 60 for a in allowed if abs(a) >= 100):
            continue
        problems.append(f"unsupported number {n}")
    for c in out.get("citations") or []:
        if c not in allowed_ids:
            problems.append(f"unknown citation {c}")
    low = body.lower()
    problems += [f"causal phrase '{p}'" for p in CAUSAL if p in low]
    problems += [f"overclaim '{p}'" for p in OVERCLAIM if p in low]
    if ev is not None:
        problems += flag_claim_problems(body, ev)
    return problems


_LAYER_WORDS = {
    "aqi": ("aqi", "air", "pollut", "station", "pm2", "pm10", "no2", "no₂"),
    "lst": ("temperature", "heat", "hot", "lst", "cool", "°c"),
    "ndvi": ("vegetation", "ndvi", "green"),
    "water": ("water",),
}


def _layer_flagged(ev: dict) -> dict[str, bool]:
    m = ev.get("models") or {}
    L = m.get("layer_isolation_forest") or {}
    return {
        "aqi": bool((L.get("aqi") or {}).get("is_anomaly")) or bool((m.get("station_isolation_forest") or {}).get("is_anomaly")),
        "lst": bool((L.get("lst") or {}).get("is_anomaly"))
               or (m.get("xgboost_lst") or {}).get("flag") in ("unexplained_heat", "unexplained_cooling"),
        "ndvi": bool((L.get("ndvi") or {}).get("is_anomaly")),
        "water": bool((L.get("water_health") or {}).get("is_anomaly"))
                 or (m.get("water_health") or {}).get("flag") in ("low_water_condition", "high_water_condition"),
    }


def flag_claim_problems(text: str, ev: dict) -> list[str]:
    """Reject sentences that say a model flagged something it did not flag."""
    flagged = _layer_flagged(ev)
    anything = any_model_flag(ev)
    out = []
    for sent in re.split(r"(?<=[.!?])\s+|\\n|\n", text.lower()):
        cleaned = re.sub(r"\b(not|no|never|isn't|is not|was not|wasn't|nor|doesn't|does not|didn't|did not|"
                         r"aren't|are not|without|neither)\s+(been\s+|be\s+|an?\s+|as\s+an?\s+|any\s+|"
                         r"model\s+|isolation forest\s+)?(flag\w*|anomal\w*|outlier\w*)", "", sent)
        if not re.search(r"\bflag(s|ged|ging)?\b|\banomal(y|ous)\b", cleaned):
            continue
        m = ev.get("models") or {}
        if re.search(r"multivariate|combined", cleaned):
            # the combined Isolation Forest names the features behind its flag
            ok = bool((m.get("isolation_forest") or {}).get("is_anomaly"))
            if not ok:
                out.append("claims a combined-model flag that the models did not raise")
            continue
        if "pollutant mix" in cleaned:
            ok = bool((m.get("station_isolation_forest") or {}).get("is_anomaly"))
            if not ok:
                out.append("claims a station flag that the models did not raise")
            continue
        layers = [k for k, words in _LAYER_WORDS.items() if any(w in cleaned for w in words)]
        ok = any(flagged[k] for k in layers) if layers else anything
        if not ok:
            what = "/".join(layers) if layers else "any model"
            out.append(f"claims a {what} flag that the models did not raise")
    return out


SUMMARY_SYSTEM = (
    "You turn GeoSense's checked findings for one map location into a short plain-English summary for a "
    "non-expert. Use ONLY the FACTS and ASSOCIATED_FACTORS given; add no new facts, numbers, places or advice. "
    "Copy any number exactly as written. Say something is 'flagged' only if STATUS says it was flagged. Never "
    "claim a cause: use 'associated with' or 'consistent with'. Water Health is a satellite proxy and AQI between "
    "stations is an estimate: never call water clean, polluted, safe or of good/poor quality, and never call air "
    "clean or safe — say 'higher/lower than most water cells' or give the AQI category. Talk only about the "
    "FOCUS_LAYER when one is given; do not bring in other layers. "
    "Return JSON only."
)


def rag_info() -> dict:
    st = retriever.corpus_stats()
    info = {"mode": retriever.retrieval_mode(), "notes": st["notes"], "passages": st["passages"],
            "documents": st["documents"]}
    try:
        ev_path = Path(__file__).resolve().parents[3] / "data" / "rag" / "retrieval_eval.json"
        res = json.loads(ev_path.read_text(encoding="utf-8"))["results"]
        best = res.get("hybrid+docs") or res.get("hybrid") or res.get("bm25")
        info.update({"recall_at_5": best["recall_at_5"], "mrr": best["mrr"], "eval_questions": best["questions"]})
    except Exception:
        pass
    return info


def ai_enabled() -> bool:
    from app.core.config import get_settings
    return (getattr(get_settings(), "ai_mode", "summary") or "summary").lower() != "off" and bool(active_provider())


def _compact_evidence(ev: dict) -> dict:
    """Smaller prompt = fewer tokens = far fewer free-tier rate limits. Same facts."""
    e = {k: v for k, v in ev.items() if k not in ("sources", "location")}
    e["models"] = {k: v for k, v in (ev.get("models") or {}).items() if v}
    return e


def _kn(passages: list[dict], n: int = 4, chars: int = 700) -> list[dict]:
    return [{"knowledge_id": p["knowledge_id"], "content": p["content"][:chars]} for p in passages[:n]]


def _factor_evidence(f: dict, city: str | None) -> dict | None:
    """Best supporting evidence for one possible factor: a page from a source document if one matches,
    otherwise the curated note the rule is based on."""
    hits = retriever.retrieve(f["text"], k=1, city=city, include_notes=False, min_score=1.5, strict=True)
    if hits:
        d = hits[0]
        return {"kind": "passage", "title": d["title"], "source": d["source"], "url": d.get("url"),
                "excerpt": d["content"][:240] + "…"}
    d = retriever.get(f["kb"])
    if d:
        return {"kind": "note", "title": d["title"], "source": d["source"], "url": d.get("url"), "excerpt": None}
    return None


def _station_count() -> int | None:
    """Number of stations behind the current city's AQI surface (None if there is no surface)."""
    try:
        rec = json.loads(city_path("surfaces", "manifest.json").read_text(encoding="utf-8"))["surfaces"].get("aqi") or {}
        return len(rec.get("stations") or []) or None
    except Exception:
        return None


def _composite_card() -> dict | None:
    """Composite v2 method card from the manifest (weights, coverage, sensitivity)."""
    import json as _json
    try:
        rec = _json.loads(city_path("surfaces", "manifest.json").read_text(encoding="utf-8"))["surfaces"].get("composite") or {}
    except Exception:
        return None
    if rec.get("version") != 2:
        return None
    return {k: rec.get(k) for k in ("weights", "inputs_used", "coverage_pixels", "min_components", "official_index")} | {
        "sensitivity": {k: (rec.get("sensitivity") or {}).get(k) for k in ("summary", "top_stable_pct", "alternatives")}}


# "Nothing here" statements: said only on that layer's own tab (where the tab would otherwise be
# empty), never on Composite or another layer's tab.
ABSENCE_OWNER = {"vegetation_unavailable": "ndvi", "heat_unavailable": "lst", "water_not_applicable": "water_health",
                 "aqi_unavailable": "aqi"}


async def explain_point(analysis: dict, use_llm: bool = True, focus: str | None = None) -> dict[str, Any]:
    ev = build_evidence(analysis)
    signals = [x for x in derive_signals(ev) if ABSENCE_OWNER.get(x["id"], focus) == focus]
    signals = focus_order(signals, focus)
    recs = recommendations(signals, focus)
    must = sorted({k for s in signals for k in s["kb"]} | {r["kb"] for r in recs} | {"pixel_cell_municipality"})
    city = get_city()
    factors = associated_factors(ev, signals, focus)
    must = sorted(set(must) | {f["kb"] for f in factors})
    det = deterministic_text(ev, signals, recs, focus, factors)
    _k = FOCUS_SIGNALS.get(focus or "", ())
    _fs = [s for s in signals if any(s["id"].startswith(k) for k in _k)] if focus in FACTOR_THEME_FOR_FOCUS else []
    cls = classification(_fs or signals)
    mitigation = mitigation_plan(ev, signals, focus)
    must = sorted(set(must) | {i["kb"] for i in mitigation["items"]})
    # the cell's own signals as the query; curated notes the rules used are always included,
    # and the best-matching document passages (with page numbers) are added as primary evidence
    factor_evidence = [_factor_evidence(f, city.id) for f in factors[:4]]

    keys = FOCUS_SIGNALS.get(focus or "", ())
    focus_signals = [s for s in signals if any(s["id"].startswith(k) for k in keys)] if focus in FACTOR_THEME_FOR_FOCUS else []
    shown = (focus_signals or signals)[:6]
    # Sources = what this tab actually shows: page-level passages from source documents that match this
    # location's findings, then the curated notes behind the displayed findings, factors and measures.
    tab_query = " ".join([x["text"] for x in shown] + [ev["municipality"] or "", city.name])
    doc_hits = retriever.retrieve(tab_query, k=4, city=city.id, include_notes=False, min_score=1.5, strict=True)
    used_notes = list(dict.fromkeys([k for x in shown for k in x["kb"]] + [f["kb"] for f in factors[:2]]
                                    + [i["kb"] for i in mitigation["items"]]))
    passages = doc_hits + [d for d in (retriever.get(k) for k in used_notes) if d]

    from app.services.ml.area_relationships import area_relationships
    relationships = area_relationships(ev, focus, n_stations=_station_count())

    result: dict[str, Any] = {
        "rag": rag_info(),
        # how the layers relate across the city, and where this 300 m area sits on each link
        "relationships": relationships,
        # the seasonal history in time order (heat first / greenery after; greening with cooling)
        "time_order": ev.get("time_order"),
        # the sub-layers behind this tab's value, each with its meaning here and its cited source
        "supporting_measures": supporting_measures(ev, focus),
        "key_findings": (focus_signals or signals)[:3],
        "mitigation": mitigation,
        "factor_evidence": factor_evidence,
        "suggested_questions": suggested_questions(ev, focus),
        "focus": focus,
        "llm_requested": bool(use_llm),
        "location": ev["location"],
        "municipality": ev["municipality"],
        "cell_code": ev["cell_code"],
        "classification": cls,
        "evidence": ev,
        "signals": signals,
        "recommendations": recs,
        "explanation": det,
        "deterministic_explanation": det["summary"] + "\n" + "\n".join(det["what_we_see"]),
        "citations": [{"knowledge_id": p["knowledge_id"], "title": p["title"], "source": p["source"],
                       "url": p.get("url"), "score": p.get("score"), "kind": p.get("kind", "note"),
                       "page": p.get("page"), "source_type": p.get("source_type"),
                       "excerpt": (p["content"][:280] + "…") if p.get("kind") == "passage" else None}
                      for p in passages],
        "generation": {"mode": "deterministic", "llm": None, "warnings": []},
        "model_cards": {**{k: v for k, v in ml_summary().items() if k in (
            "isolation_forest", "xgboost_lst", "water_health", "layer_isolation_forest",
            "station_isolation_forest", "snapshot_at", "relationships", "validation")},
            "composite": _composite_card()},
    }

    if not use_llm or not ai_enabled():
        if use_llm and not ai_enabled():
            result["generation"]["warnings"].append("AI summary off (AI_MODE=off or no key) — evidence write-up only.")
        return result

    # a single-layer view: the AI only sees that layer's facts, so it cannot drift to other layers
    facts = [x["text"] for x in (focus_signals or signals)[:8]]
    why = [f["text"] for f in factors[:4]]
    # an area that is clearly off the city-wide pattern (e.g. warmer than typical for its vegetation)
    why += [r["here"]["text"] for r in relationships
            if r.get("here") and r["here"]["verdict"] != "about typical"][:1]
    user = json.dumps({
        "FOCUS_LAYER": FOCUS_LABEL.get(focus or "", "all layers"),
        "STATUS": {"anomaly": "flagged by at least one model", "elevated": "elevated but not flagged as an outlier",
                   "notice": "notable but not flagged", "inlier": "nothing unusual"}[cls],
        "FACTS": facts, "ASSOCIATED_FACTORS": why,
        "OUTPUT_SCHEMA": {"plain_summary": "2-3 short sentences for a non-expert, at most 70 words"},
    }, ensure_ascii=False)
    try:
        out, meta = await complete_json(SUMMARY_SYSTEM, user)
        # output rail: strict schema (Pydantic) + secrets/links/markup scan, then the evidence check
        parsed, problems = parse_output(SummaryOut, out)
        summary = parsed.plain_summary if parsed else ""
        if parsed:
            allowed = " ".join(facts + why)
            problems = validate_llm({"plain_summary": summary}, allowed, set(), ev)
        if problems:
            result["generation"] = {"mode": "deterministic", "llm": meta,
                                    "warnings": ["AI summary not shown (failed the evidence check: " + "; ".join(problems[:3]) + ")"]}
        else:
            result["ai_summary"] = summary
            result["generation"] = {"mode": "llm_summary", "llm": meta, "warnings": []}
    except LLMUnavailable as exc:
        result["generation"]["warnings"].append(str(exc))
    return result


# ── Ask GeoSense: data-aware suggested questions with rule-based answers ─────────
CPCB_HEALTH = {
    "Good": "minimal impact",
    "Satisfactory": "minor breathing discomfort to sensitive people",
    "Moderate": "breathing discomfort to people with lung disease such as asthma, and discomfort to people with "
                "heart disease, children and older adults",
    "Poor": "breathing discomfort to most people on prolonged exposure",
    "Very Poor": "respiratory illness on prolonged exposure",
    "Severe": "respiratory effects even on healthy people, and serious health impacts on people with lung or heart "
              "disease",
}


def _dev(ev: dict, layer: str, feature: str) -> dict | None:
    L = ((ev.get("models") or {}).get("layer_isolation_forest") or {}).get(layer) or {}
    return next((d for d in L.get("dominant_deviations") or [] if d.get("feature") == feature), None), L


def suggested_questions(ev: dict, focus: str | None) -> list[dict]:
    """Questions that make sense for THIS spot (no false premises such as 'why is it low' when it is high)."""
    px, cf = ev["area"], ev["cell"]["features"]
    has_water = px.get("water_health") is not None or cf.get("wh_mean") is not None
    has_lst = cf.get("lst_mean") is not None or px.get("lst_c") is not None
    has_ndvi = px.get("ndvi") is not None or cf.get("ndvi_mean") is not None
    has_aqi = px.get("aqi") is not None
    wd = _water_dominated(cf)
    Q = {
        "ndvi": [("ndvi_level", "How green is this place?"), ("ndvi_nearby", "Is it greener than the area around it?"),
                 ("action", "What protects the green edges here?" if wd else "What would increase green cover here?")]
                if has_ndvi else
                [("ndvi_none", "Why is there no vegetation value here?")],
        "lst": [("lst_level", "How hot is this place?"), ("lst_explained", "Is it hotter than its land cover explains?"),
                ("action", "What keeps this area cool?" if wd else "What would cool this block?")] if has_lst else
               [("lst_none", "Why is there no temperature value here?")],
        "water_health": [("water_level", "How does this water compare with other water?"),
                         ("water_nearby", "Is this water better or worse than nearby water?"),
                         ("water_confirm", "How can this be confirmed on the ground?")] if has_water else
                        [("water_none", "Why is there no Water Health value here?")],
        "aqi": [("aqi_level", "What does this AQI mean for health?"), ("aqi_pollutant", "Which pollutant dominates nearby?"),
                ("action", "What would reduce pollution here?")] if has_aqi else
               [("aqi_none", "Why is AQI unavailable here?")],
        "composite": [("overview", "What stands out here?"), ("action", "What would help most here?"),
                      ("reliability", "How reliable is this analysis?")],
    }
    hist_key = {"lst": "lst", "ndvi": "ndvi", "water_health": "wh"}.get(focus or "")
    h = ev.get("history") or {}
    has_hist = (bool((h.get("metrics") or {}).get(hist_key)) if hist_key else
                bool((h.get("station") or {}).get("change")) if focus == "aqi" else bool(h.get("metrics")))
    qs = list(Q.get(focus or "composite", Q["composite"]))
    if has_hist:
        qs.append(("history", "How has this changed over the years?"))
    return [{"id": i, "q": q} for i, q in qs]


def _pct_word(p) -> str:
    return "" if p is None else f" (percentile {p:.0f})"


def intent_answer(intent: str, ev: dict, signals: list[dict], focus: str | None) -> tuple[str, list[str]]:
    """Answer built only from this spot's evidence. Returns (text, knowledge ids used)."""
    px, cf, pct, m = ev["area"], ev["cell"]["features"], ev["cell"]["city_percentiles"], ev["models"]
    x = m.get("xgboost_lst") or {}
    w = m.get("water_health") or {}
    st = px.get("aqi_nearest_station") or {}

    if intent == "ndvi_level":
        parts = []
        if px.get("ndvi") is not None:
            parts.append(f"Vegetation {_where(ev, 'ndvi')}: NDVI {px['ndvi']:.2f} ({px['ndvi_band']}).")
        if cf.get("ndvi_mean") is not None:
            parts.append(f"Across this 300 m cell the mean NDVI is {cf['ndvi_mean']:.2f}, greener than "
                         f"{pct.get('ndvi_mean') or 0:.0f}% of cells; dense vegetation covers {_share(cf.get('veg_frac'))} "
                         f"and bare/built-up surface {_share(cf.get('built_frac'))}.")
        parts.append("NDVI above about 0.6 means dense vegetation; below 0.2 means bare or built-up ground.")
        return " ".join(parts), ["ndvi_ranges"]
    if intent == "ndvi_nearby":
        d, L = _dev(ev, "ndvi", "ndvi_local_diff")
        if not d or d.get("value") is None:
            return "A comparison with the surrounding area is not available for this cell.", ["layer_isolation_forest"]
        word = "greener" if d["value"] > 0 else "less green"
        flag = ("The vegetation Isolation Forest flags this cell as unusual." if L.get("is_anomaly")
                else "The vegetation Isolation Forest does not flag this cell as unusual.")
        return (f"Its NDVI is {abs(d['value']):.2f} {word} than the average of cells within 1 km "
                f"({d['z']:+.1f} standard deviations). {flag}"), ["layer_isolation_forest"]
    if intent == "lst_level":
        parts = []
        if cf.get("lst_mean") is not None:
            parts.append(f"The cell's mean land surface temperature is {cf['lst_mean']:.1f} °C, hotter than "
                         f"{pct.get('lst_mean') or 0:.0f}% of cells.")
        if px.get("lst_c") is not None:
            parts.append(f"Land surface temperature {_where(ev, 'lst')} is {px['lst_c']:.1f} °C.")
        parts.append("This is the surface ('skin') temperature at the satellite pass, not the air temperature people feel.")
        return " ".join(parts), ["landsat_lst", "lst_vs_air"]
    if intent == "lst_explained":
        if not x:
            return "The temperature model has no result for this cell (not enough cloud-free data).", ["cloud_gaps"]
        verdict = {"unexplained_heat": "beyond twice that error, so it is flagged as unexplained heat",
                   "unexplained_cooling": "beyond twice that error, so it is flagged as unexplained cooling"}.get(
            x.get("flag"), "within the normal range, so the temperature is consistent with the land cover")
        drivers = ", ".join(_fmt_driver(d) for d in (x.get("top_drivers") or [])[:2])
        return (f"From its land cover the XGBoost model expects {x['expected_lst_c']} °C; Landsat observed "
                f"{x['observed_lst_c']} °C, a difference of {x['residual_c']:+.1f} °C. The model's typical error is "
                f"{x['cv_rmse_c']} °C, so this is {verdict}. Largest modelled contributions: {drivers}."), \
            ["residual_interpretation", "xgboost_shap"]
    if intent == "water_level":
        wh = px.get("water_health") if px.get("water_health") is not None else cf.get("wh_mean")
        p = w.get("percentile") if w else city_percentile("wh_mean", wh)
        flag = {"low_water_condition": "The Water Health model flags it as low condition.",
                "high_water_condition": "The Water Health model flags it as better than usual."}.get(
            w.get("flag"), "The Water Health model does not flag it.")
        return (f"Water Health here is {wh:.3f}, higher than {p or 0:.0f}% of water cells in the region. {flag} "
                "Higher values mean fewer optical signs of algae or suspended sediment. It is a satellite proxy, "
                "not a lab measurement."), ["water_health_geosense"]
    if intent == "water_nearby":
        d, L = _dev(ev, "water_health", "wh_local_diff")
        if not d or d.get("value") is None:
            return "A comparison with nearby water is not available for this cell.", ["layer_isolation_forest"]
        word = "better" if d["value"] > 0 else "worse"
        flag = ("The Water Health Isolation Forest flags it as unusual." if L.get("is_anomaly")
                else "The Water Health Isolation Forest does not flag it as unusual.")
        return (f"Its Water Health index is {abs(d['value']):.3f} {word} than nearby water within 1 km "
                f"({d['z']:+.1f} standard deviations). {flag}"), ["layer_isolation_forest", "water_health_geosense"]
    if intent == "water_confirm":
        return ("Ask the state pollution control board or the municipal corporation to take water samples and test dissolved oxygen (DO), BOD, pH "
                "and faecal coliforms, the National Water Quality Monitoring Programme parameters. A site visit can "
                "also check for sewage outfalls, dumping and water hyacinth."), ["water_quality_insitu"]
    if intent == "aqi_level":
        cat = px.get("aqi_category")
        return (f"AQI {_where(ev, 'aqi')} is {px['aqi']} ({cat}, CPCB scale). CPCB's health statement for {cat}: "
                f"{CPCB_HEALTH.get(cat, 'see CPCB guidance')}. The nearest station is {st.get('station_name')}, "
                f"{st.get('distance_m')} m away; values between stations are estimates."), \
            ["aqi_health_statements", "idw_method"]
    if intent == "aqi_pollutant":
        dom = st.get("dominant_pollutant")
        if not dom:
            return "The nearest station's pollutant breakdown is not available.", ["openaq_caaqms"]
        subs = {POLLUTANT_NAMES.get(k, k): v for k, v in (st.get("sub_indices") or {}).items() if v is not None}
        detail = ", ".join(f"{k} {v:g}" for k, v in sorted(subs.items(), key=lambda kv: -kv[1]))
        return (f"At the nearest station ({st.get('station_name')}, {st.get('distance_m')} m away) the dominant "
                f"pollutant is {POLLUTANT_NAMES.get(dom, dom)}, typically associated with "
                f"{POLLUTANT_ASSOC.get(dom, 'several sources')}. CPCB sub-indices: {detail}."), \
            ["pollutant_signatures", "aqi_cpcb_scale"]
    if intent == "action":
        plan = mitigation_plan(ev, signals, focus, n=3)
        if not plan["items"]:
            return plan.get("note") or "No specific measure is indicated here.", []
        items = "; ".join(("★ " if i["fits_this_cell"] else "") + i["text"].rstrip(".") for i in plan["items"])
        return f"{plan['title']}: {items}. (★ = fits this spot's data.)", sorted({i["kb"] for i in plan["items"]})
    if intent == "overview":
        top = [x_["text"] for x_ in signals if x_["level"] != "info"][:2] or [x_["text"] for x_ in signals[:2]]
        return " ".join(top) or "No unusual signal at this spot.", ["pixel_cell_municipality"]
    if intent == "history":
        keys = FOCUS_SIGNALS.get(focus or "", ())
        hs = [x for x in _history_signals(ev.get("history"))
              if not keys or focus == "composite" or any(x["id"].startswith(k) for k in keys)]
        if not hs:
            return ("There is no seasonal history for this layer at this spot yet (history is built from dry-season "
                    "satellite composites since 2023; cloudy seasons stay missing).", ["history_method"])
        return " ".join(x["text"] for x in hs[:4]), ["history_method"]

    if intent == "reliability":
        r2 = x.get("cv_r2")
        acc = f"The temperature model explains about half the variation (R² {r2}, ±{x.get('cv_rmse_c')} °C on unseen areas). " if r2 else ""
        return (acc + "Isolation Forest marks the most unusual 5% of cells as outliers, which shows where to look, not a cause. "
                "AQI between stations is interpolated, Water Health is a satellite proxy, and all satellite values "
                "come from one snapshot, so trends are not shown."), ["spatial_cv", "isolation_forest", "idw_method"]
    none_msgs = {
        "ndvi_none": ("No valid Sentinel-2 vegetation value here (cloud or outside coverage); nothing is filled in.", ["cloud_gaps"]),
        "lst_none": ("No cloud-free Landsat temperature here in the current composite; nothing is filled in.", ["cloud_gaps"]),
        "water_none": ("No water was detected at this point or in this 300 m cell (MNDWI), so Water Health does not "
                       "apply here.", ["mndwi"]),
        "aqi_none": ((next((g for g in ev.get("data_gaps", []) if g.startswith("CPCB AQI")), None)
                      or "No fresh official station data covers this point."), ["openaq_caaqms"]),
    }
    return none_msgs.get(intent, ("I can only answer questions about this location's data.", []))


INTENT_WORDS = (
    ("history", ("over time", "over the years", "changed", "trend", "history", "last year", "past years",
                 "getting worse", "getting better", "compared to before", "previous year")),
    ("aqi_pollutant", ("pollutant", "no2", "pm10", "pm2", "ozone", "so2", "dominat")),
    ("aqi_level", ("aqi", "air", "pollution", "smog", "health", "breath", "risk", "safe")),
    ("water_confirm", ("confirm", "sample", "test", "ground", "verify", "lab")),
    ("water_nearby", ("nearby water", "other water near", "compared to nearby")),
    ("water_level", ("water",)),
    ("lst_explained", ("land cover", "explain", "expected", "unexplained", "xgboost")),
    ("lst_level", ("hot", "heat", "temperature", "warm", "cool", "lst")),
    ("ndvi_nearby", ("around", "nearby", "surround")),
    ("ndvi_level", ("green", "vegetation", "tree", "ndvi")),
    ("action", ("what would", "what can", "how can we", "improve", "reduce", "help", "mitigat", "should")),
    ("reliability", ("reliable", "accura", "trust", "confiden")),
    ("overview", ("stand out", "stands out", "standing out", "summary", "summar", "overall", "what is happening",
                  "what's happening", "notable", "important here", "key point")),
)


def match_intent(question: str, ev: dict, focus: str | None) -> str | None:
    """Map a typed question to one of the data intents available for this spot (any tab)."""
    q = question.lower()
    available = {x["id"] for f in ("ndvi", "lst", "water_health", "aqi", "composite")
                 for x in suggested_questions(ev, f)}
    prefer = {"ndvi": "ndvi", "lst": "lst", "water_health": "water", "aqi": "aqi"}.get(focus or "")
    hits = [i for i, words in INTENT_WORDS if any(wd in q for wd in words)]
    if prefer:  # on a tab, prefer that layer's meaning for ambiguous words
        hits.sort(key=lambda i: not i.startswith(prefer))
    # "what would cool this block?" is a request for action, not for the temperature value
    if "action" in hits and re.search(r"\b(what would|what can|how can|how do we|improve|reduce|mitigat|should we|"
                                      r"increase|lower|fix)\b", q):
        hits.remove("action")
        hits.insert(0, "action")
    if "history" in hits:   # "has it got hotter over the years?" asks about change, not the current value
        hits.remove("history")
        hits.insert(0, "history")
    for intent in hits:
        if intent in available:
            return intent
        none_id = intent.split("_")[0] + "_none"
        if none_id in available:
            return none_id
    return None


QA_SYSTEM = (
    "You answer a user's question about ONE map location in GeoSense ({region}). Use ONLY "
    "the FACTS, DATA_ANSWER and KNOWLEDGE given; copy numbers exactly; add no new numbers, places or advice. Answer "
    "the question that was asked, directly, in at most 90 words. If the question assumes something the facts "
    "contradict (e.g. 'why is it low' when it is high), say so politely and give the actual situation. Say a model "
    "'flags' something only if the FACTS say so. Never claim a cause ('associated with' is fine). Never call water "
    "clean, polluted, safe or of good/poor quality, or air clean or safe. If the question cannot be answered from "
    "these inputs, set answer to exactly OUT_OF_SCOPE. Return JSON only."
)


def _cites(ids) -> list[dict]:
    out = []
    for kid in dict.fromkeys(ids):
        d = retriever.get(kid)
        if d:
            out.append({"knowledge_id": d["knowledge_id"], "title": d["title"], "source": d["source"], "url": d.get("url"),
                        "kind": d.get("kind", "note"), "page": d.get("page"), "source_type": d.get("source_type")})
    return out


async def answer_question(question: str, analysis: dict | None = None, focus: str | None = None,
                          intent: str | None = None) -> dict[str, Any]:
    """Ask GeoSense.

    * Suggested questions (intent given) are answered by rules from this spot's own data — always consistent.
    * Typed questions: the AI answers from the spot's facts + retrieved knowledge and is validated; if the AI is
      off/fails, the matching data answer is used; if nothing matches, the user is told what can be answered.
    """
    ev = build_evidence(analysis) if analysis else None
    signals = focus_order(derive_signals(ev), focus) if ev else []
    suggestions = suggested_questions(ev, focus) if ev else []

    # input rail (typed questions only; suggested questions are fixed text from the app)
    if not intent:
        verdict = check_question(question)
        if not verdict.allowed:
            return {"answer": verdict.message, "mode": "guardrail", "guardrail": verdict.category, "intent": None,
                    "citations": [], "warnings": []}

    if ev and intent:
        text, kb = intent_answer(intent, ev, signals, focus)
        return {"answer": text, "mode": "evidence", "intent": intent, "citations": _cites(kb), "warnings": []}

    matched = match_intent(question, ev, focus) if ev else None
    data_text, data_kb = intent_answer(matched, ev, signals, focus) if matched else (None, [])

    if ai_enabled():
        # retrieval rail: retrieved text is data, never instructions
        passages = sanitize_passages(retriever.retrieve(question, k=4, city=get_city().id,
                                                        must_include=list(data_kb)))
        user = json.dumps({
            "QUESTION": question, "FOCUS_LAYER": FOCUS_LABEL.get(focus or "", "all layers"),
            "FACTS": [x["text"] for x in signals[:8]], "DATA_ANSWER": data_text,
            "KNOWLEDGE": _kn(passages, 4),
            "OUTPUT_SCHEMA": {"answer": "str (<= 90 words) or OUT_OF_SCOPE", "citations": ["knowledge_id"]},
        }, ensure_ascii=False, default=str)
        try:
            out, meta = await complete_json(QA_SYSTEM.replace("{region}", get_city().region_label), user)
            # output rail: strict schema (Pydantic) + secrets/links/markup scan
            parsed, schema_problems = parse_output(AnswerOut, out)
            ans = parsed.answer if parsed else ""
            if schema_problems:
                warn = "AI answer not shown (failed the output check)."
            elif ans and ans != "OUT_OF_SCOPE":
                allowed = json.dumps(ev, default=str) + " " + (data_text or "") + " " + \
                    " ".join(x["text"] for x in signals) + " " + " ".join(p["content"] for p in passages)
                problems = validate_llm({"answer": ans}, allowed, {p["knowledge_id"] for p in passages}, ev)
                if not problems:
                    used = [c for c in parsed.citations if c in {p["knowledge_id"] for p in passages}]
                    return {"answer": ans, "mode": "llm_validated", "llm": meta, "intent": matched,
                            "citations": _cites(used or data_kb or [p["knowledge_id"] for p in passages[:2]]),
                            "warnings": []}
                warn = "AI answer not shown (failed the evidence check)."
            else:
                warn = "AI could not answer this from the available data."
        except LLMUnavailable as exc:
            warn = str(exc)
    else:
        warn = "AI off — answered from this location's data."

    if data_text:
        return {"answer": data_text, "mode": "evidence", "intent": matched, "citations": _cites(data_kb),
                "warnings": [warn] if warn and "off" not in warn else []}
    tips = "; ".join(f"“{x['q']}”" for x in suggestions) if suggestions else "questions about a clicked location"
    return {"answer": "I can only answer questions about this location's data and the cited knowledge base. "
                      f"Try: {tips}", "mode": "out_of_scope", "intent": None, "citations": [],
            "warnings": [warn] if warn and "off" not in warn else []}
