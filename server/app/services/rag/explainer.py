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

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from app.services.qc import LST_QC_MIN_C
from app.services.rag import retriever
from app.services.rag.llm import LLMUnavailable, active_provider, complete_json

ML_SUMMARY = Path(__file__).resolve().parents[3] / "data" / "ml" / "ml_summary.json"
CAUSAL = ("caused by", "because of", "is due to", "responsible for", "results from", "leads to")
# Satellite proxies and interpolated AQI cannot certify quality or safety.
OVERCLAIM = ("good water quality", "water quality is good", "water is clean", "clean water", "safe water",
             "safe to drink", "drinkable", "safe to swim", "polluted water", "water is polluted", "contaminated",
             "water quality is poor", "poor water quality", "air is clean", "clean air", "air is safe",
             "safe to breathe", "healthy air", "no pollution", "pollution-free")


@lru_cache(maxsize=1)
def _summary_cached(mtime: float) -> dict:
    return json.loads(ML_SUMMARY.read_text(encoding="utf-8"))


def ml_summary() -> dict:
    if not ML_SUMMARY.exists():
        return {}
    return _summary_cached(ML_SUMMARY.stat().st_mtime)


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
                                                   "water_frac", "lst_mean", "lst_std", "wh_mean", "dist_water_m", "aqi_idw")}
    if cell_feats.get("dist_water_m") is not None:
        cell_feats["dist_water_m"] = round(cell_feats["dist_water_m"])
    pct = {k: city_percentile(k, feats.get(k)) for k in ("ndvi_mean", "built_frac", "veg_frac", "lst_mean", "wh_mean")}

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
        gaps.append(f"LST pixel below {LST_QC_MIN_C:.0f} °C flagged as probable residual cloud and not interpreted.")
    if not aqi_b.get("available"):
        gaps.append("CPCB AQI unavailable: " + (aqi_b.get("reason") or "no fresh station coverage").rstrip(".") + ".")
    if not models:
        gaps.append("No ML results stored for this cell yet (run scripts/run_ml_pipeline.py).")

    return {
        "location": analysis.get("location"),
        "municipality": muni,
        "cell_code": cell.get("cell_code"),
        "pixel": {
            "ndvi": _r(ndvi_px), "ndvi_band": ndvi_band(ndvi_px),
            "lst_c": _r(lst_px, 1),
            "water_health": _r(pv("water_health")),
            "aqi": aqi_b.get("value") if aqi_b.get("available") else None,
            "aqi_category": (aqi_b.get("category") or {}).get("name") if aqi_b.get("available") else None,
            "aqi_nearest_station": aqi_b.get("nearest_station") if aqi_b.get("available") else None,
            "composite_stress": _r(pv("composite")),
        },
        "cell": {"features": cell_feats, "city_percentiles": pct},
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


# ─────────────────────────────────────────────────────────────────────────────
# 2. Deterministic signals + recommendations
# ─────────────────────────────────────────────────────────────────────────────

def derive_signals(ev: dict) -> list[dict[str, Any]]:
    S: list[dict[str, Any]] = []
    px, cf, pct, m = ev["pixel"], ev["cell"]["features"], ev["cell"]["city_percentiles"], ev["models"]

    if px["ndvi"] is not None:
        S.append({"id": "vegetation_pixel", "level": "info", "kb": ["ndvi_ranges"],
                  "text": f"The clicked pixel has NDVI {px['ndvi']:.2f} ({px['ndvi_band']})."})
    if cf.get("built_frac") is not None and pct.get("built_frac") is not None:
        if pct["built_frac"] >= 75:
            S.append({"id": "built_up", "level": "notice", "kb": ["uhi", "ndvi_season_mumbai"],
                      "text": f"{cf['built_frac']*100:.0f}% of this 300 m cell is bare/built-up surface "
                              f"(higher than {pct['built_frac']:.0f}% of cells in the study region)."})
        elif cf.get("veg_frac") is not None and (pct.get("veg_frac") or 0) >= 75:
            S.append({"id": "green_cell", "level": "info", "kb": ["vegetation_cooling"],
                      "text": f"{cf['veg_frac']*100:.0f}% of this cell is dense vegetation "
                              f"(greener than {pct['veg_frac']:.0f}% of cells)."})

    if cf.get("lst_mean") is not None and pct.get("lst_mean") is not None:
        p = pct["lst_mean"]
        lvl = "warning" if p >= 85 else "notice" if p >= 70 else "info"
        word = ("among the hottest cells" if p >= 85 else "hotter than most cells" if p >= 70
                else "cooler than most cells" if p <= 30 else "typical for the study region")
        S.append({"id": "heat_cell", "level": lvl, "kb": ["landsat_lst", "lst_vs_air"],
                  "text": f"Cell mean land surface temperature is {cf['lst_mean']:.1f} °C — {word} "
                          f"(percentile {p:.0f})."})
    if px["lst_c"] is not None:
        S.append({"id": "heat_pixel", "level": "info", "kb": ["lst_vs_air"],
                  "text": f"The exact Landsat pixel (30 m) reads {px['lst_c']:.1f} °C."})

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

    if px["water_health"] is not None:
        wp = city_percentile("wh_mean", px["water_health"])
        S.append({"id": "water_pixel" if (wp is None or wp > 20) else "water_pixel_low",
                  "level": "info" if (wp is None or wp > 20) else "notice",
                  "kb": ["water_health_geosense", "mndwi", "ndci"],
                  "text": f"Detected water at this pixel; Water Health index {px['water_health']:.3f}"
                          + (f" (percentile {wp:.0f} among water cells)." if wp is not None else ".")})
    if px["water_health"] is None and cf.get("wh_mean") is not None:
        wp = city_percentile("wh_mean", cf["wh_mean"])
        S.append({"id": "water_cell", "level": "info", "kb": ["water_health_geosense"],
                  "text": f"The clicked pixel itself is not detected as water (MNDWI), but this 300 m cell contains water "
                          f"with a mean Water Health index of "
                          f"{cf['wh_mean']:.3f}" + (f" (percentile {wp:.0f} among water cells)." if wp is not None else ".")})
    w = m.get("water_health")
    if w and w.get("flag") == "low_water_condition":
        S.append({"id": "water_low", "level": "warning", "kb": ["water_health_geosense", "turbidity_proxy", "water_quality_insitu"],
                  "text": f"This cell's water bodies score {w['wh_mean']:.3f}, {abs(w['robust_z']):.1f} robust-σ below "
                          f"the median water cell — an optical stress signal (algal/turbidity proxies), not a lab result."})

    if px["aqi"] is not None:
        lvl = "warning" if px["aqi"] > 200 else "notice" if px["aqi"] > 100 else "info"
        st = px.get("aqi_nearest_station") or {}
        S.append({"id": "aqi", "level": lvl, "kb": ["aqi_cpcb_scale", "aqi_health_statements", "idw_method"],
                  "text": f"Interpolated CPCB AQI here is {px['aqi']} ({px['aqi_category']}); nearest station "
                          f"{st.get('station_name')} is {st.get('distance_m')} m away."})
    if px["aqi"] is None:
        gap = next((g for g in ev.get("data_gaps", []) if g.startswith("CPCB AQI")), None)
        S.append({"id": "aqi_unavailable", "level": "info", "kb": ["openaq_caaqms", "idw_method"],
                  "text": gap or "CPCB AQI is not available at this point (no fresh station coverage within range)."})
    st = px.get("aqi_nearest_station") or {}
    if px["aqi"] is not None and st.get("dominant_pollutant"):
        names = {"pm25": "PM2.5", "pm10": "PM10", "no2": "NO₂", "so2": "SO₂", "o3": "O₃", "co": "CO"}
        subs = {names.get(k, k): v for k, v in (st.get("sub_indices") or {}).items() if v is not None}
        detail = ", ".join(f"{k} {v:g}" for k, v in sorted(subs.items(), key=lambda kv: -kv[1]))
        S.append({"id": "aqi_station_mix", "level": "info", "kb": ["aqi_cpcb_scale", "mumbai_air_sources"],
                  "text": f"At the nearest station ({st.get('station_name')}) the dominant pollutant is "
                          f"{names.get(st['dominant_pollutant'], st['dominant_pollutant'])} (station AQI {st.get('aqi')})"
                          + (f"; CPCB sub-indices: {detail}." if detail else ".")})
    sif = m.get("station_isolation_forest")
    if sif and sif.get("is_anomaly"):
        devs = "; ".join(f"{d['pollutant']} sub-index {d['sub_index']} ({d['z']:+.1f}σ)"
                         for d in (sif.get("dominant_deviations") or [])[:2])
        S.append({"id": "station_outlier", "level": "notice", "kb": ["station_isolation_forest", "mumbai_air_sources"],
                  "text": f"The nearest station ({sif['station_name']}) has an unusual pollutant mix compared with the "
                          f"other stations (station Isolation Forest): {devs}."})
    return S


FOCUS_SIGNALS = {
    "ndvi": ("vegetation", "built_up", "green_cell", "layer_ndvi"),
    "lst": ("heat_cell", "heat_pixel", "unexplained_", "heat_explained", "heat_unavailable", "layer_lst"),
    "water_health": ("water_", "layer_water_health"),
    "aqi": ("aqi", "layer_aqi", "station_outlier"),  # includes aqi_station_mix
    "composite": ("multivariate_outlier",),
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
    "water": ("mitigate_water", "Check for sewage outfalls, dumping or hyacinth growth and request MPCB/municipal sampling "
                                "(DO, BOD, coliforms) to confirm the satellite signal."),
    "air": ("mitigate_air", "On Moderate-or-worse days limit prolonged outdoor exertion for sensitive groups; local dust "
                            "control and stopping waste burning reduce PM."),
    "inspect": ("isolation_forest", "The combination of values here is unusual for the region (see the deviations above). Check the "
                                    "block on recent imagery or on site before acting — the flag says where to look, not why."),
    "keep": ("mitigate_greening", "This location is environmentally favourable relative to the city; the main action is to "
                                  "protect its vegetation and water from conversion."),
}


def recommendations(signals: list[dict]) -> list[dict]:
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
    return [{"kb": RECOMMENDATIONS[k][0], "text": RECOMMENDATIONS[k][1], "theme": k} for k in out]


def classification(signals: list[dict]) -> str:
    if any(s["level"] == "warning" for s in signals):
        return "anomaly" if any(s["id"] in ("multivariate_outlier", "unexplained_heat", "water_low")
                                or (s["id"].startswith("layer_") and s["level"] == "warning") for s in signals) else "elevated"
    return "notice" if any(s["level"] == "notice" for s in signals) else "inlier"


POLLUTANT_NAMES = {"pm25": "PM2.5", "pm10": "PM10", "no2": "NO₂", "so2": "SO₂", "o3": "O₃", "co": "CO"}
POLLUTANT_ASSOC = {
    "no2": "traffic and other fuel combustion",
    "pm10": "road and construction dust and re-suspended particles",
    "pm25": "combustion sources such as vehicles, industry and open waste burning",
    "so2": "industrial and fuel-oil combustion",
    "o3": "a secondary pollutant formed in sunlight from NOx and VOC emissions",
    "co": "incomplete combustion",
}
FACTOR_THEME_FOR_FOCUS = {"lst": "heat", "ndvi": "veg", "water_health": "water", "aqi": "air"}


def _share(v) -> str:
    return "n/a" if v is None else f"{v * 100:.0f}%"


def associated_factors(ev: dict, signals: list[dict], focus: str | None = None) -> list[dict]:
    """Rule-based "possible associated factors" built only from this cell's evidence and
    cited knowledge. Always phrased as associations; never a cause."""
    F: list[dict] = []
    m, cf, pct, px = ev["models"], ev["cell"]["features"], ev["cell"]["city_percentiles"], ev["pixel"]
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

    if "built_up" in ids or "layer_ndvi_outlier" in ids:
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

    want = FACTOR_THEME_FOR_FOCUS.get(focus or "")
    if want:
        F = [f for f in F if f["theme"] == want] + [f for f in F if f["theme"] != want]
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
        ("miyawaki", "mitigate_greening", "Dense native-species (Miyawaki-style) plantations on open plots."),
        ("campus", "mitigate_greening", "Greening of school, hospital and institutional campuses."),
    ]},
    "water_health": {"title": "Improve the water body", "items": [
        ("sample", "water_quality_insitu", "Confirm on the ground first: MPCB / municipal sampling of DO, BOD and coliforms."),
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


def mitigation_plan(ev: dict, signals: list[dict], focus: str | None = None, n: int = 4) -> dict:
    """Layer-specific mitigation strategies, with the ones that fit this cell's evidence first."""
    cf, pct, px, m = ev["cell"]["features"], ev["cell"]["city_percentiles"], ev["pixel"], ev["models"]
    ids = {s["id"] for s in signals}
    built_hi = (pct.get("built_frac") or 0) >= 70
    veg_lo = (cf.get("veg_frac") if cf.get("veg_frac") is not None else 1) < 0.15
    hot = (pct.get("lst_mean") or 0) >= 70 or "unexplained_heat" in ids or "layer_lst_outlier" in ids
    water_low = bool({"water_low", "water_pixel_low"} & ids) or \
        (m.get("layer_isolation_forest") or {}).get("water_health", {}).get("direction") == "low"
    has_water = cf.get("wh_mean") is not None or px.get("water_health") is not None
    dom = (px.get("aqi_nearest_station") or {}).get("dominant_pollutant")
    aqi = px.get("aqi")

    why = {
        "cool_roofs": built_hi and "large built-up share", "shade_trees": veg_lo and "very little tree cover",
        "heat_warning": hot and "among the hotter cells", "keep_open": has_water and "water nearby",
        "street_trees": built_hi and "large built-up share", "protect_green": (pct.get("veg_frac") or 0) >= 60 and "existing dense greenery",
        "miyawaki": veg_lo and "very little tree cover",
        "sample": water_low and "low Water Health signal", "sewage": water_low and "low Water Health signal",
        "dust_sites": dom == "pm10" and "PM10 dominant at nearest station",
        "road_dust": dom == "pm10" and "PM10 dominant at nearest station",
        "burning": dom == "pm25" and "PM2.5 dominant at nearest station",
        "traffic": dom == "no2" and "NO₂ dominant at nearest station",
        "industry": dom == "so2" and "SO₂ dominant at nearest station",
        "exposure": aqi is not None and aqi > 100 and "AQI is Moderate or worse",
    }

    def pick(layer: str, k: int) -> list[dict]:
        rows = [{"key": key, "kb": kb, "text": text, "fits_this_cell": bool(why.get(key)),
                 "why": why.get(key) or None, "layer": layer} for key, kb, text in MITIGATION[layer]["items"]]
        rows.sort(key=lambda r: not r["fits_this_cell"])  # stable: matching ones first, catalogue order kept
        return rows[:k]

    if focus in MITIGATION:
        if focus == "water_health" and not has_water:
            return {"layer": focus, "title": MITIGATION[focus]["title"], "applicable": False,
                    "note": "No water detected in this cell, so water-body measures do not apply here.", "items": []}
        if focus == "aqi" and aqi is None:
            items = pick("aqi", n)
            return {"layer": focus, "title": MITIGATION[focus]["title"], "applicable": True,
                    "note": "AQI is unavailable at this point; general measures are shown.", "items": items}
        return {"layer": focus, "title": MITIGATION[focus]["title"], "applicable": True, "items": pick(focus, n)}

    # composite: the two most relevant measures from each layer that applies here
    layers = [l for l, ok in (("lst", hot or built_hi), ("ndvi", veg_lo or built_hi), ("water_health", water_low),
                              ("aqi", aqi is not None and aqi > 100)) if ok] or ["ndvi"]
    items = [r for l in layers for r in pick(l, 2)][:6]
    return {"layer": "composite", "title": "Priority measures for this location", "applicable": True, "items": items}


FOCUS_LABEL = {"ndvi": "NDVI / vegetation", "lst": "LST / surface heat", "water_health": "Water Health",
               "aqi": "CPCB AQI / air quality", "composite": "all layers combined"}


def deterministic_text(ev: dict, signals: list[dict], recs: list[dict], focus: str | None = None,
                       factors: list[dict] | None = None) -> dict[str, Any]:
    where = f"{ev['municipality'] or 'the study region'} (cell {ev['cell_code'] or 'n/a'})"
    keys = FOCUS_SIGNALS.get(focus or "", ())
    pool = [s for s in signals if any(s["id"].startswith(k) for k in keys)] if keys else []
    pool = pool or signals
    warnings = [s for s in pool if s["level"] == "warning"]
    notices = [s for s in pool if s["level"] == "notice"]
    head = warnings[0]["text"] if warnings else notices[0]["text"] if notices else (
        pool[0]["text"] if pool else "No valid satellite observation at this point.")
    return {
        "headline": f"{where}: " + (["Flagged by GeoSense models", "Elevated signal", "Notable conditions", "No unusual signal"]
                                    [["anomaly", "elevated", "notice", "inlier"].index(classification(signals))]),
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
        cleaned = re.sub(r"\b(not|no|never|isn't|is not|was not|wasn't|nor)\s+(been\s+|be\s+)?flag\w*", "", sent)
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


SYSTEM = (
    "You are GeoSense's environmental analyst for Mumbai, Thane and Mira-Bhayandar. Explain one map location "
    "to a city official in plain English. Use ONLY numbers that appear in EVIDENCE or KNOWLEDGE. Never invent "
    "measurements; if something is missing say it is unavailable. Use associative language ('associated with', "
    "'consistent with', 'the model flags') — never claim causes. Satellite Water Health is a proxy, not lab data; "
    "interpolated AQI is an estimate. Cite knowledge by knowledge_id. Lead with the FOCUS_LAYER the user is viewing, "
    "then mention other layers briefly. Say a model 'flags' something ONLY when that model's is_anomaly is true or "
    "its flag is unexplained_heat, unexplained_cooling, low_water_condition or high_water_condition; otherwise say "
    "the value is 'above/below the city norm' or 'not flagged'. Round percentages to whole numbers and temperatures "
    "to one decimal. Do not invent recommendations beyond RECOMMENDATION_THEMES. Never call water clean, polluted, "
    "safe or of good/poor quality, and never call air clean or safe (proxies and estimates cannot certify that). "
    "Return JSON only."
)


SUMMARY_SYSTEM = (
    "You turn GeoSense's checked findings for one map location into a short plain-English summary for a "
    "non-expert. Use ONLY the FACTS and ASSOCIATED_FACTORS given; add no new facts, numbers, places or advice. "
    "Copy any number exactly as written. Say something is 'flagged' only if STATUS says it was flagged. Never "
    "claim a cause: use 'associated with' or 'consistent with'. Water Health is a satellite proxy and AQI between "
    "stations is an estimate: never call water clean, polluted, safe or of good/poor quality, and never call air "
    "clean or safe — say 'higher/lower than most water cells' or give the AQI category. Lead with the FOCUS_LAYER. "
    "Return JSON only."
)


def rag_info() -> dict:
    info = {"mode": retriever.retrieval_mode(), "notes": len(retriever.load_kb())}
    try:
        ev_path = Path(__file__).resolve().parents[3] / "data" / "rag" / "retrieval_eval.json"
        res = json.loads(ev_path.read_text(encoding="utf-8"))["results"]
        best = res.get("hybrid") or res.get("bm25")
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


async def explain_point(analysis: dict, use_llm: bool = True, focus: str | None = None) -> dict[str, Any]:
    ev = build_evidence(analysis)
    signals = focus_order(derive_signals(ev), focus)
    recs = recommendations(signals)
    must = sorted({k for s in signals for k in s["kb"]} | {r["kb"] for r in recs} | {"pixel_cell_municipality"})
    query = " ".join([s["text"] for s in signals] + [ev["municipality"] or "", "mumbai"])
    passages = retriever.retrieve(query, k=6, city=ev["municipality"], must_include=must)
    factors = associated_factors(ev, signals, focus)
    must = sorted(set(must) | {f["kb"] for f in factors})
    passages = retriever.retrieve(query, k=6, city=ev["municipality"], must_include=must)
    det = deterministic_text(ev, signals, recs, focus, factors)
    cls = classification(signals)
    mitigation = mitigation_plan(ev, signals, focus)
    must = sorted(set(must) | {i["kb"] for i in mitigation["items"]})
    passages = retriever.retrieve(query, k=6, city=ev["municipality"], must_include=must)

    result: dict[str, Any] = {
        "rag": rag_info(),
        "mitigation": mitigation,
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
                       "url": p.get("url"), "score": p["score"]} for p in passages],
        "generation": {"mode": "deterministic", "llm": None, "warnings": []},
        "model_cards": {k: v for k, v in ml_summary().items() if k in (
            "isolation_forest", "xgboost_lst", "water_health", "layer_isolation_forest",
            "station_isolation_forest", "snapshot_at")},
    }

    if not use_llm or not ai_enabled():
        if use_llm and not ai_enabled():
            result["generation"]["warnings"].append("AI summary off (AI_MODE=off or no key) — evidence write-up only.")
        return result

    facts = [x["text"] for x in signals[:8]]
    why = [f["text"] for f in factors[:4]]
    user = json.dumps({
        "FOCUS_LAYER": FOCUS_LABEL.get(focus or "", "all layers"),
        "STATUS": {"anomaly": "flagged by at least one model", "elevated": "elevated but not flagged as an outlier",
                   "notice": "notable but not flagged", "inlier": "nothing unusual"}[cls],
        "FACTS": facts, "ASSOCIATED_FACTORS": why,
        "OUTPUT_SCHEMA": {"plain_summary": "2-3 short sentences for a non-expert, at most 70 words"},
    }, ensure_ascii=False)
    try:
        out, meta = await complete_json(SUMMARY_SYSTEM, user)
        summary = (out.get("plain_summary") or "").strip()
        allowed = " ".join(facts + why)
        problems = validate_llm({"plain_summary": summary}, allowed, set(), ev)
        if not summary:
            problems.append("empty summary")
        if len(summary.split()) > 90:
            problems.append("summary too long")
        if problems:
            result["generation"] = {"mode": "deterministic", "llm": meta,
                                    "warnings": ["AI summary not shown (failed the evidence check: " + "; ".join(problems[:3]) + ")"]}
        else:
            result["ai_summary"] = summary
            result["generation"] = {"mode": "llm_summary", "llm": meta, "warnings": []}
    except LLMUnavailable as exc:
        result["generation"]["warnings"].append(str(exc))
    return result


async def answer_question(question: str, analysis: dict | None = None, focus: str | None = None) -> dict[str, Any]:
    """Grounded Q&A: retrieval over the knowledge base (+ point evidence when given)."""
    ev = build_evidence(analysis) if analysis else None
    signals = focus_order(derive_signals(ev), focus) if ev else []
    city = ev["municipality"] if ev else None
    q = question.lower()
    expand = ""
    if any(w in q for w in ("water", "lake", "river", "creek", "algae", "turbid")):
        expand += " water health turbidity algae chlorophyll NDCI MNDWI water quality"
    if any(w in q for w in ("hot", "heat", "temperature", "warm", "lst")):
        expand += " surface heat built-up vegetation cooling land surface temperature"
    if any(w in q for w in ("air", "aqi", "pollut", "pm2", "pm10", "no2", "ozone", "dust", "smog")):
        expand += " AQI CPCB particulate pollution sources"
    if any(w in q for w in ("green", "tree", "vegetation", "ndvi")):
        expand += " NDVI vegetation greening"
    FOCUS_EXPAND = {"water_health": " water health turbidity algae NDCI MNDWI in-situ water quality sampling",
                    "lst": " surface heat land surface temperature built-up vegetation cooling",
                    "ndvi": " NDVI vegetation greening tree cover",
                    "aqi": " AQI CPCB particulate pollution stations"}
    if not expand and focus in FOCUS_EXPAND:
        expand = FOCUS_EXPAND[focus]
    if expand:
        passages = retriever.retrieve(question + expand, k=6, city=city)
    else:
        # generic question ("what stands out?", "what would improve this area?"): ground the
        # retrieval in this location's strongest signals instead of loose keyword matches
        strong = [x for x in signals if x["level"] != "info"] or signals
        must = list(dict.fromkeys(k for x in strong[:3] for k in x["kb"]))
        passages = retriever.retrieve(question + " " + " ".join(x["text"] for x in strong[:3]),
                                      k=6, city=city, must_include=must)
    cites = [{"knowledge_id": p["knowledge_id"], "title": p["title"], "source": p["source"], "url": p.get("url")} for p in passages]

    generic = {"pixel_cell_municipality", "robust_z", "spatial_cv", "residual_interpretation", "xgboost_shap"}
    asked_method = any(w in q for w in ("pixel", "cell", "municipal", "z-score", "robust", "model", "xgboost", "shap", "residual"))
    content = [p for p in passages if asked_method or p["knowledge_id"] not in generic]
    parts = []
    topic_ids = (("water",) if any(w in q for w in ("water", "lake", "river", "creek", "algae", "turbid")) else ()) \
        + (("heat", "built", "unexplained", "green") if any(w in q for w in ("hot", "heat", "temperature", "warm", "lst")) else ()) \
        + (("aqi", "station") if any(w in q for w in ("air", "aqi", "pollut", "pm2", "pm10", "no2", "ozone", "dust", "smog")) else ())
    if not topic_ids and focus in ("water_health", "lst", "ndvi", "aqi"):
        topic_ids = {"water_health": ("water",), "lst": ("heat", "unexplained", "layer_lst"),
                     "ndvi": ("vegetation", "built", "green", "layer_ndvi"), "aqi": ("aqi", "station")}[focus]
    topical = [s_ for s_ in signals if any(t in s_["id"] for t in topic_ids)] if topic_ids else []
    topical = topical or [s_ for s_ in signals if s_["level"] != "info"] or signals[:1]
    if signals:
        parts.append("What the data shows here: " + " ".join(t["text"] for t in topical[:2]))
    for p in content[:2]:
        sents = re.split(r"(?<=[.!?])\s+", p["content"])
        parts.append(f"{p['title']}: " + " ".join(sents[:2]))
    if any(w in q for w in ("why", "reason", "cause", "because")):
        parts.append("Note: these are statistical associations from one satellite snapshot. The reason cannot be "
                     "confirmed from this data alone; on-site checks or sampling would be needed.")
    recs = recommendations(signals) if signals else []
    action = any(w in q for w in ("do ", "help", "reduce", "improve", "fix", "mitigat", "action", "increase",
                                  "cool", "what would", "what can", "how can", "should"))
    if action:
        theme_by_focus = {"ndvi": "green", "lst": "heat", "water_health": "water", "aqi": "air"}
        theme_by_words = ("green" if any(w in q for w in ("green", "tree", "vegetat")) else
                          "heat" if any(w in q for w in ("cool", "heat", "hot", "temperature")) else
                          "water" if "water" in q else "air" if any(w in q for w in ("air", "aqi", "pollut")) else None)
        want = theme_by_words or theme_by_focus.get(focus or "")
        pick = next((r for r in recs if r["theme"] == want), None) if want else None
        if pick is None and want in RECOMMENDATIONS:
            pick = {"kb": RECOMMENDATIONS[want][0], "text": RECOMMENDATIONS[want][1], "theme": want}
        pick = pick or (recs[0] if recs else None)
        if pick is None:
            k = "keep" if any(x["id"] in ("green_cell", "multivariate_outlier_favourable") for x in signals) else "inspect"
            pick = {"kb": RECOMMENDATIONS[k][0], "text": RECOMMENDATIONS[k][1], "theme": k}
        if pick:
            parts.append("What could help: " + pick["text"])
            if pick["kb"] not in {c["knowledge_id"] for c in cites}:
                kb = retriever.get(pick["kb"]) if hasattr(retriever, "get") else None
                if kb:
                    cites.append({"knowledge_id": kb["knowledge_id"], "title": kb["title"],
                                  "source": kb["source"], "url": kb.get("url")})
    fallback = {
        "answer": " ".join(parts) if parts else "I don't have curated knowledge on that yet.",
        "evidence_used": [s_["text"] for s_ in signals],
        "mode": "extractive",
    }
    if not ai_enabled():
        return {**fallback, "citations": cites,
                "warnings": ["AI off (AI_MODE=off or no key) — answer built from the evidence and knowledge base."]}
    user = json.dumps({"QUESTION": question, "FOCUS_LAYER": FOCUS_LABEL.get(focus or "", "all layers"),
                       "EVIDENCE": _compact_evidence(ev) if ev else None, "SIGNALS": [s["text"] for s in signals],
                       "KNOWLEDGE": _kn(passages, 4),
                       "OUTPUT_SCHEMA": {"answer": "str (<=150 words)", "citations": ["knowledge_id"]}},
                      ensure_ascii=False, default=str)
    try:
        out, meta = await complete_json(SYSTEM, user)
        problems = validate_llm(out, json.dumps(ev, default=str) + " ".join(p["content"] for p in passages),
                                {p["knowledge_id"] for p in passages}, ev)
        if problems:
            return {**fallback, "citations": cites, "warnings": ["LLM answer rejected: " + "; ".join(problems[:5])], "llm": meta}
        return {"answer": out.get("answer"), "evidence_used": [s["text"] for s in signals], "mode": "llm_validated",
                "citations": [c for c in cites if c["knowledge_id"] in set(out.get("citations") or [])] or cites,
                "llm": meta, "warnings": []}
    except LLMUnavailable as exc:
        return {**fallback, "citations": cites, "warnings": [str(exc)]}