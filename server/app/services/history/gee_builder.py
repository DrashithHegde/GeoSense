"""Seasonal per-cell statistics from Earth Engine (runs on the user's machine).

For each season: the same cloud masks and indices as the current GeoSense layers, median
composites over the season, then zonal statistics per 300 m cell computed on the source pixels
(reduceRegions, 10 m). Cells with too few valid pixels get NULL — never a filled value.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from app.services.history.seasons import Season

SERVER_ROOT = Path(__file__).resolve().parents[3]
HISTORY_DIR = SERVER_ROOT / "data" / "history"
COLUMNS = ["cell_id", "ndvi", "veg_frac", "built_frac", "openwater_frac", "ndmi_veg", "ndbi_land",
           "water_frac", "wh", "lst", "s2_valid_frac", "lst_valid_frac"]
MIN_VALID = 0.30          # same rule as the current cell features
MIN_VEG_PX_10M = 40       # 4,000 m² of vegetation for a moisture value
MIN_WATER_PX_10M = 30     # 3,000 m² of detected water for a Water Health value


def season_image(season: Season, region) -> tuple[Any, int, int]:
    import ee

    from app.services.qc import LST_QC_MIN_C
    from app.services.surfaces.water_health_surface import build_water_mask
    from gee.ingest_lst import add_lst_celsius, mask_landsat_l2
    from gee.ingest_ndvi_ndwi import S2_DATASET, add_indices, mask_s2_sr

    start, end = season.start.isoformat(), season.end_exclusive
    s2 = (ee.ImageCollection(S2_DATASET).filterDate(start, end).filterBounds(region)
          .select(["B3", "B4", "B5", "B8", "B11", "QA60"]).map(mask_s2_sr).map(add_indices)
          .map(lambda i: i.addBands(i.normalizedDifference(["B8", "B11"]).rename("NDMI"))))
    ls = (ee.ImageCollection("LANDSAT/LC08/C02/T1_L2").filterDate(start, end).filterBounds(region)
          .merge(ee.ImageCollection("LANDSAT/LC09/C02/T1_L2").filterDate(start, end).filterBounds(region)))
    n_s2, n_ls = int(s2.size().getInfo()), int(ls.size().getInfo())

    comp = s2.median()
    ndvi = comp.select("NDVI")
    ndmi = comp.select("NDMI")
    water = build_water_mask(comp)
    algal = ee.Image(1).subtract(comp.select("NDCI_PROXY").add(1).divide(2).clamp(0, 1))
    susp = ee.Image(1).subtract(comp.select("TURBIDITY_PROXY").add(1).divide(2).clamp(0, 1))
    wh = algal.add(susp).divide(2).clamp(0, 1).updateMask(water)
    lst = ls.map(mask_landsat_l2).map(add_lst_celsius).median().select("LST")
    lst = lst.updateMask(lst.gte(LST_QC_MIN_C))
    ones = ee.Image(1)
    img = ee.Image.cat([
        ndvi.rename("ndvi"),
        ndvi.gte(0.5).rename("veg"),
        ndvi.gte(0).And(ndvi.lt(0.2)).rename("built"),
        ndvi.lt(0).rename("ow"),
        ndmi.updateMask(ndvi.gte(0.4)).rename("ndmiveg"),
        ndmi.updateMask(ndvi.gte(0)).rename("ndmiland"),
        water.unmask(0).updateMask(ndvi.mask()).rename("wm"),
        wh.rename("wh"),
        lst.rename("lst"),
        ones.updateMask(ndvi.mask()).unmask(0).rename("s2v"),
        ones.updateMask(lst.mask()).unmask(0).rename("lstv"),
        ones.rename("total"),
    ])
    return img, n_s2, n_ls


def to_row(p: dict[str, Any]) -> dict[str, Any]:
    """Apply the validity rules to one cell's raw reduceRegions properties."""
    g = p.get
    s2v, lstv = g("s2v_mean"), g("lstv_mean")
    ok = s2v is not None and s2v >= MIN_VALID

    def m(band):
        return g(f"{band}_mean") if ok else None

    ndmi_land = g("ndmiland_mean") if ok and (g("ndmiland_count") or 0) >= MIN_VALID * (g("total_count") or 1) else None
    return {
        "cell_id": int(p["cell_id"]),
        "ndvi": m("ndvi"), "veg_frac": m("veg"), "built_frac": m("built"), "openwater_frac": m("ow"),
        "ndmi_veg": g("ndmiveg_mean") if ok and (g("ndmiveg_count") or 0) >= MIN_VEG_PX_10M else None,
        "ndbi_land": None if ndmi_land is None else -ndmi_land,
        "water_frac": m("wm"),
        "wh": g("wh_mean") if (g("wh_count") or 0) >= MIN_WATER_PX_10M else None,
        "lst": g("lst_mean") if lstv is not None and lstv >= MIN_VALID else None,
        "s2_valid_frac": s2v, "lst_valid_frac": lstv,
    }


def build_season(season: Season, cells, region) -> dict[str, Any]:
    import ee

    from gee.cell_reducer import reduce_cells

    img, n_s2, n_ls = season_image(season, region)
    reducer = ee.Reducer.mean().combine(ee.Reducer.count(), sharedInputs=True)
    raw = reduce_cells(img, reducer, 10, cells, label=season.key)
    rows = [to_row(p) for p in raw]
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = HISTORY_DIR / f"cells_{season.key}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return {"season": season.key, "label": season.label, "kind": season.kind, "year": season.year,
            "period_start": season.start.isoformat(), "period_end": season.end.isoformat(),
            "partial": season.partial, "matched_for": season.matched_for,
            "s2_images": n_s2, "landsat_images": n_ls, "cells": len(rows), "file": path.name}
