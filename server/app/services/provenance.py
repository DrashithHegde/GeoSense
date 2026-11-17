"""Data provenance and freshness per layer, read from the surface manifest (single source of truth).

One normalised record per layer: where the data comes from, which dates it covers, its real
resolution, how many images/stations went into it, when it was generated and how old it is.
Shown as a small badge on each layer and in Deep Analysis.
"""
from __future__ import annotations
from app.core.cities import city_path

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANIFEST = city_path("surfaces", "manifest.json")
FRESH_DAYS = 30  # satellite composites older than this are marked "older"

LAYERS = {
    "ndvi": {"label": "Vegetation (NDVI)", "sensor": "Sentinel-2 (ESA)", "unit": "index -1..1"},
    "lst": {"label": "Land Surface Temperature", "sensor": "Landsat 8/9 (USGS)", "unit": "°C",
            "resolution_note": "thermal band native 100 m, delivered on a 30 m grid"},
    "water_health": {"label": "Water Health", "sensor": "Sentinel-2 (ESA)", "unit": "index 0..1 (spectral proxy)"},
    "aqi": {"label": "Air Quality (CPCB AQI)", "sensor": "CPCB-network ground stations via OpenAQ", "unit": "CPCB AQI"},
    "composite": {"label": "Composite Environmental Stress", "sensor": "derived from the layers above",
                  "unit": "index 0..1 (GeoSense-derived)"},
    "ndmi": {"label": "Vegetation moisture (NDMI)", "sensor": "Sentinel-2 (ESA)", "unit": "index -1..1"},
    "ndbi": {"label": "Built-up index (NDBI)", "sensor": "Sentinel-2 (ESA)", "unit": "index -1..1"},
}


def _date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        try:
            d = datetime.strptime(str(s)[:15], "%Y%m%dT%H%M%S")
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _age_days(d: datetime | None, now: datetime) -> int | None:
    return None if d is None else max(0, (now - d).days)


def layer_provenance(metric: str, rec: dict[str, Any], surfaces: dict[str, Any],
                     now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    meta = LAYERS.get(metric, {"label": metric, "sensor": rec.get("source"), "unit": None})
    base = {"layer": metric, "label": meta["label"], "sensor": meta["sensor"], "unit": meta["unit"],
            "status": rec.get("generation_status") or ("generated" if rec else "missing"),
            "generated_at": rec.get("generated_at"), "method": rec.get("methodology")}
    if not rec or base["status"] not in ("generated",):
        return {**base, "available": False, "reason": rec.get("reason") or "not generated yet"}

    if metric == "aqi":
        st = rec.get("stations") or []
        obs = sorted(d for d in (_date(s.get("observed_at")) for s in st) if d)
        newest = obs[-1] if obs else None
        out = {**base, "available": True, "stations": len(st),
               "observed_from": obs[0].isoformat() if obs else None,
               "observed_to": newest.isoformat() if newest else None,
               "age_hours": None if newest is None else round((now - newest).total_seconds() / 3600, 1),
               "freshness_rule": "stations older than 48 h are excluded",
               "resolution": "point stations; IDW estimate on a ~270 m grid between them",
               "validation_mae": (rec.get("validation") or {}).get("mae")}
        out["freshness"] = "current" if (out["age_hours"] or 1e9) <= 48 else "stale"
        out["short"] = f"{len(st)} CPCB-network stations · ≤48 h"
        return out

    period = rec.get("source_period") or {}
    if metric == "composite":
        lst = surfaces.get("lst") or {}
        period = lst.get("source_period") or period
    start, end = period.get("start"), period.get("end")
    end_d = _date(end) or _date(rec.get("source_timestamp")) or _date(rec.get("timestamp"))
    res = rec.get("source_scale_m") or rec.get("scale_m") or (30 if metric == "composite" else None)
    out = {**base, "available": True, "dataset": rec.get("dataset"),
           "period_start": start, "period_end": end or (end_d.date().isoformat() if end_d else None),
           "resolution_m": res, "resolution_note": meta.get("resolution_note") or rec.get("resolution_note"),
           "images": rec.get("image_count") or rec.get("images_found"),
           "age_days": _age_days(end_d, now)}
    out["freshness"] = "current" if (out["age_days"] is not None and out["age_days"] <= FRESH_DAYS) else "older"
    if metric == "composite":
        out["inputs"] = rec.get("inputs_used")
        out["version"] = rec.get("version")
        out["official_index"] = False
    if rec.get("derived_from"):
        out["derived_from"] = rec["derived_from"]
    when = end_d.strftime("%d %b %Y") if end_d else "date unknown"
    sensor = "GeoSense-derived" if metric == "composite" else meta["sensor"].split(" (")[0]
    out["short"] = " · ".join(x for x in (sensor, f"{res:g} m" if res else None,
                                         f"{out['images']} images" if out.get("images") else None, when) if x)
    return out


def all_provenance(manifest_path: Path = MANIFEST, now: datetime | None = None) -> dict[str, Any]:
    try:
        surfaces = json.loads(manifest_path.read_text(encoding="utf-8")).get("surfaces") or {}
    except Exception:
        surfaces = {}
    return {m: layer_provenance(m, surfaces.get(m) or {}, surfaces, now) for m in LAYERS}
