"""Composite Environmental Stress surface (rewritten, no imputation).

Inputs (all real, read from the scientific GeoTIFFs in the manifest):
  heat       = Landsat LST (QC >= LST_QC_MIN_C), scaled by in-region p5..p95
  greenness  = 1 - Sentinel-2 NDVI/0.8 (vegetation deficit), NDVI averaged to 30 m
  air        = CPCB AQI / 300, ONLY if a station-based AQI surface is generated

A pixel gets a composite value only where every included input is valid.
Nothing is filled. Weights are renormalised over the inputs actually used and
recorded in the manifest. Water Health is not included (it only exists on water).

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

from app.services.surfaces.heatmap_render import (  # noqa: E402
    VIBRANT_STOPS, RenderSpec, legend_stops, mapbox_coordinates_for, render_heatmap, save_png,
    sha256, study_region_mask,
)

DATA = SERVER_ROOT / "data" / "surfaces"
MANIFEST = DATA / "manifest.json"
NODATA = -9999.0
WEIGHTS = {"heat": 0.4, "greenness": 0.35, "air": 0.25}
from app.services.qc import LST_QC_MIN_C  # noqa: E402


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
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    S = manifest["surfaces"]
    lst_path = _tif(S["lst"], "lst")
    with rasterio.open(lst_path) as ref:
        lst = ref.read(1).astype("float32")
        lst[(lst == ref.nodata) | (lst < LST_QC_MIN_C)] = np.nan
        transform, profile = ref.transform, ref.profile
        ndvi = _read_on(_tif(S["ndvi"], "ndvi"), ref)
        aqi = None
        if (S.get("aqi") or {}).get("generation_status") == "generated":
            aqi = _read_on(DATA / S["aqi"]["geotiff_filename"], ref)

    region = study_region_mask(lst.shape, transform)
    p5, p95 = np.nanpercentile(lst[region], [5, 95])
    comps = {
        "heat": np.clip((lst - p5) / (p95 - p5), 0, 1),
        "greenness": 1.0 - np.clip(ndvi / 0.8, 0, 1),
    }
    if aqi is not None:
        comps["air"] = np.clip(aqi / 300.0, 0, 1)
    used = list(comps)
    wsum = sum(WEIGHTS[k] for k in used)
    weights = {k: WEIGHTS[k] / wsum for k in used}
    stack = np.stack([comps[k] for k in used])
    # open water (NDVI < 0) is not land stress -> excluded, not scored
    valid = np.all(np.isfinite(stack), axis=0) & region & (ndvi >= 0.0)
    score = np.full(lst.shape, NODATA, dtype="float32")
    score[valid] = sum(weights[k] * comps[k][valid] for k in used)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = DATA / "composite"
    out_dir.mkdir(parents=True, exist_ok=True)
    tif = out_dir / f"composite_{ts}.tif"
    profile.update(dtype="float32", nodata=NODATA, compress="deflate", count=1)
    with rasterio.open(tif, "w", **profile) as dst:
        dst.write(score, 1)

    knots = list(np.linspace(0.05, 0.85, len(VIBRANT_STOPS)))
    # reverse palette: low stress = teal, high stress = magenta
    spec = RenderSpec(metric="composite", stops_rgb=list(reversed(VIBRANT_STOPS)), knot_values=knots,
                      stop_labels=["very low", "low", "mild", "moderate", "elevated", "high", "very high"],
                      sharp_sigma=0.9, glow_sigma=3.0, halo_sigma=8.0, sharp_alpha=215, glow_alpha=110, halo_alpha=60)
    out = render_heatmap(score, valid, transform, spec)
    names = {k: f"{tif.stem}_{k}.png" for k in ("sharp", "glow", "halo")}
    sums = {k: save_png(out[k], out_dir / names[k]) for k in names}

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
        "inputs_used": used,
        "weights": weights,
        "lst_scaling_c": {"p5": float(p5), "p95": float(p95)},
        "methodology": "Weighted environmental stress from real LST + NDVI" + (" + CPCB AQI" if aqi is not None else ""),
        "interpretation": "0 = low combined stress, 1 = high. Relative index for exploration, not a regulatory measure.",
        "nodata_semantics": "transparent where any included input is missing (no imputation) or on open water (NDVI < 0)",
        "valid_pixels": int(valid.sum()),
        "visualization": {"stops": legend_stops(spec),
                          "legend": {"left_label": "LOW STRESS", "right_label": "HIGH STRESS",
                                     "range": {"min": knots[0], "max": knots[-1]}}},
        "generation_status": "generated",
    }
    tmp = MANIFEST.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(MANIFEST)
    print(json.dumps({"tif": tif.name, "inputs_used": used, "weights": weights, "valid_pixels": int(valid.sum())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
