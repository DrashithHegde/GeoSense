"""Composite Environmental Stress surface v2 (no imputation, coverage-aware).

Method: app/services/composite_v2.py — heat (LST), surface condition (vegetation deficit on
land / Water Health deficit on water) and air (CPCB AQI, where a station surface exists),
weights 0.40 / 0.35 / 0.25 renormalised over the components present, >= 2 of 3 required.
Writes the composite GeoTIFF (band 1 = score) plus a 3-band components GeoTIFF so every
click can show what contributed, and a weighting-sensitivity analysis in the manifest.

    python scripts/generate_composite_surface.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT

SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT))

from app.core.cities import city_path  # noqa: E402

from app.services.surfaces.heatmap_render import (  # noqa: E402
    STRESS_STOPS, RenderSpec, legend_stops, mapbox_coordinates_for, render_heatmap, layer_style, save_layers,
    sha256, study_region_mask,
)

DATA = city_path("surfaces")
MANIFEST = city_path("surfaces", "manifest.json")
NODATA = -9999.0
from app.services.qc import lst_qc_min_c  # noqa: E402


def _tif(rec: dict, folder: str) -> Path:
    if rec.get("geotiff_filename"):
        return DATA / rec["geotiff_filename"]
    return DATA / folder / rec["files"]["geotiff"]


def _read_on(path: Path, ref) -> np.ndarray:
    with rasterio.open(path) as src, WarpedVRT(src, crs=ref.crs, transform=ref.transform, width=ref.width,
                                               height=ref.height, resampling=Resampling.average,
                                               src_nodata=src.nodata, nodata=np.nan) as vrt:
        return vrt.read(1).astype("float32")


def main() -> int:
    from app.services.composite_v2 import (CITATION, COMPONENTS, METHOD_NOTE, MIN_COMPONENTS, WEIGHTS, combine,
                                           compute_components, sensitivity)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    S = manifest["surfaces"]
    lst_path = _tif(S["lst"], "lst")
    with rasterio.open(lst_path) as ref:
        lst = ref.read(1).astype("float32")
        lst[(lst == ref.nodata) | (lst < lst_qc_min_c())] = np.nan
        transform, profile = ref.transform, ref.profile
        ndvi = _read_on(_tif(S["ndvi"], "ndvi"), ref)
        wh = None
        if (S.get("water_health") or {}).get("generation_status") == "generated":
            wh = _read_on(_tif(S["water_health"], "water-health"), ref)
        aqi = None
        from app.services.surfaces.aqi_station_surface import aqi_expired
        if (S.get("aqi") or {}).get("generation_status") == "generated" and not aqi_expired(S["aqi"]):
            aqi = _read_on(DATA / S["aqi"]["geotiff_filename"], ref)   # expired AQI (> 48 h) is left out

    region = study_region_mask(lst.shape, transform)
    comps = compute_components(lst, ndvi, wh, aqi, region)
    score_nan, cover = combine(comps)
    valid = np.isfinite(score_nan) & region
    score = np.where(valid, score_nan, NODATA).astype("float32")
    used = [k for k in COMPONENTS if np.isfinite(comps[k][region]).any()]
    sens = sensitivity(comps)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = DATA / "composite"
    out_dir.mkdir(parents=True, exist_ok=True)
    tif = out_dir / f"composite_{ts}.tif"
    profile.update(dtype="float32", nodata=NODATA, compress="deflate", count=1)
    with rasterio.open(tif, "w", **profile) as dst:
        dst.write(score, 1)
    comp_tif = out_dir / f"composite_components_{ts}.tif"
    with rasterio.open(comp_tif, "w", **{**profile, "count": len(COMPONENTS)}) as dst:
        for i, k in enumerate(COMPONENTS, start=1):
            band = np.where(np.isfinite(comps[k]) & valid, comps[k], NODATA).astype("float32")
            dst.write(band, i)
            dst.set_band_description(i, k)
    weights = dict(WEIGHTS)
    coverage = {f"{n}_of_3": int(((cover == n) & valid).sum()) for n in (2, 3)}

    knots = list(np.linspace(0.05, 0.85, len(STRESS_STOPS)))
    # low stress = calm teal, high stress = red / crimson
    spec = RenderSpec(metric="composite", stops_rgb=STRESS_STOPS, knot_values=knots,
                      stop_labels=["very low", "low", "mild", "moderate", "elevated", "high", "very high"],
                      **layer_style("composite"))
    out = render_heatmap(score, valid, transform, spec)
    names, sums = save_layers(out, out_dir, tif.stem)

    S["composite"] = {
        "metric": "composite",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_timestamp": S["lst"].get("timestamp"),
        "geotiff_filename": f"composite/{tif.name}",
        "png_filename": f"composite/{names['sharp']}",
        "sharp_png_filename": f"composite/{names['sharp']}",
        "glow_png_filename": f"composite/{names['glow']}",
        "halo_png_filename": f"composite/{names['halo']}",
        "checksums": {"geotiff_sha256": sha256(tif), "sharp_png_sha256": sums["sharp"],
                      "glow_png_sha256": sums["glow"], "halo_png_sha256": sums["halo"]},
        "mapbox_coordinates": mapbox_coordinates_for(out["transform"], out["shape"]),
        "components_filename": f"composite/{comp_tif.name}",
        "components": list(COMPONENTS),
        "version": 2,
        "inputs_used": used,
        "weights": weights,
        "weights_note": "Documented expert weights, renormalised per pixel over the components present.",
        "min_components": MIN_COMPONENTS,
        "coverage_pixels": coverage,
        "scaling": comps["scaling"],
        "lst_scaling_c": comps["scaling"]["lst_c"],
        "sensitivity": sens,
        "methodology": "Composite v2: " + METHOD_NOTE,
        "citation": CITATION,
        "official_index": False,
        "interpretation": "0 = low combined stress, 1 = high. GeoSense-derived relative index, not an official "
                          "government index or a regulatory measure.",
        "nodata_semantics": "transparent where fewer than 2 of 3 components are valid; missing inputs are never "
                            "treated as zero or healthy",
        "valid_pixels": int(valid.sum()),
        "visualization": {"stops": legend_stops(spec),
                          "legend": {"left_label": "LOW STRESS", "right_label": "HIGH STRESS",
                                     "range": {"min": knots[0], "max": knots[-1]}}},
        "generation_status": "generated",
    }
    tmp = MANIFEST.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(MANIFEST)
    print(json.dumps({"tif": tif.name, "inputs_used": used, "weights": weights, "valid_pixels": int(valid.sum()),
                      "coverage_pixels": coverage, "sensitivity": sens.get("summary")}, indent=2))
    return 0


if __name__ == "__main__":
    from app.core.cities import run_script_for_city
    raise SystemExit(run_script_for_city(main))
