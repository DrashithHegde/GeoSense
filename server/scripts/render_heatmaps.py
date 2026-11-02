"""Re-render smooth, vibrant, boundary-clipped heatmap PNGs from the existing
scientific GeoTIFFs (NDVI, Water Health, LST). No new data is fetched and the
GeoTIFFs are never modified — clicks keep reading exact raw pixels.

Usage (from server/):
    python scripts/render_heatmaps.py                # all three
    python scripts/render_heatmaps.py --only water_health
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT))

from app.services.surfaces.heatmap_render import (  # noqa: E402
    THERMAL_STOPS,
    VIBRANT_STOPS,
    WATER_BLUE_STOPS,
    RenderSpec,
    legend_stops,
    mapbox_coordinates_for,
    quantile_knots,
    read_raster,
    render_heatmap,
    save_png,
    study_region_mask,
)

SURFACE_ROOT = SERVER_ROOT / "data" / "surfaces"
MANIFEST = SURFACE_ROOT / "manifest.json"
RENDER_VERSION = "v3"

# LST below this is physically implausible for coastal Mumbai at Landsat overpass
# (~10:30 IST) and indicates residual cloud contamination. Hidden in the display and
# excluded from cell statistics; the raw GeoTIFF pixel is still returned on click
# together with a QC flag.
from app.services.qc import LST_QC_MIN_C  # noqa: E402


def _load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _save_manifest(manifest: dict) -> None:
    tmp = MANIFEST.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(MANIFEST)


def _tif_path(record: dict, folder: str) -> Path:
    rel = record.get("geotiff_filename")
    if rel and (SURFACE_ROOT / rel).exists():
        return SURFACE_ROOT / rel
    return SURFACE_ROOT / folder / record["files"]["geotiff"]


def _in_region_values(values, valid, transform):
    region = study_region_mask(values.shape, transform)
    return values[valid & region]


def _write_three(out, folder: str, stem: str) -> dict:
    names = {k: f"{stem}_{RENDER_VERSION}_{k}.png" for k in ("sharp", "glow", "halo")}
    sums = {k: save_png(out[k], SURFACE_ROOT / folder / names[k]) for k in names}
    return {"names": names, "sums": sums}


def render_ndvi(manifest: dict) -> dict:
    rec = manifest["surfaces"]["ndvi"]
    tif = _tif_path(rec, "ndvi")
    values, valid, transform, _ = read_raster(tif)
    # NDVI < 0 is open water / bare wet surface: no vegetation signal -> transparent.
    veg_valid = valid & (values >= 0.0)
    knots = [0.0, 0.1, 0.2, 0.35, 0.5, 0.65, 0.8]  # physically interpretable NDVI scale
    spec = RenderSpec(
        metric="ndvi",
        stops_rgb=VIBRANT_STOPS,
        knot_values=knots,
        stop_labels=["bare / built", "very sparse", "sparse", "moderate", "healthy", "dense", "very dense"],
        downsample=2, sharp_sigma=1.1, glow_sigma=4.0, halo_sigma=11.0,
        sharp_alpha=225, glow_alpha=120, halo_alpha=70,
    )
    out = render_heatmap(values, veg_valid, transform, spec)
    stem = tif.stem
    w = _write_three(out, "ndvi", stem)
    region_vals = _in_region_values(values, valid, transform)
    rec.update({
        "png_filename": f"ndvi/{w['names']['sharp']}",
        "sharp_png_filename": f"ndvi/{w['names']['sharp']}",
        "glow_png_filename": f"ndvi/{w['names']['glow']}",
        "halo_png_filename": f"ndvi/{w['names']['halo']}",
        "mapbox_coordinates": mapbox_coordinates_for(out["transform"], out["shape"]),
    })
    rec["files"].update({"png": w["names"]["sharp"], "sharp_png": w["names"]["sharp"],
                         "glow_png": w["names"]["glow"], "halo_png": w["names"]["halo"]})
    rec.setdefault("checksums", {}).update({
        "png_sha256": w["sums"]["sharp"], "sharp_png_sha256": w["sums"]["sharp"],
        "glow_png_sha256": w["sums"]["glow"], "halo_png_sha256": w["sums"]["halo"],
    })
    rec["visualization"] = {
        "renderer": f"heatmap_render {RENDER_VERSION}",
        "layers": ["halo", "glow", "sharp"],
        "stops": legend_stops(spec),
        "legend": {"left_label": "LOW · 0.0", "right_label": "HIGH · 0.8+", "unit": "NDVI",
                   "range": {"min": knots[0], "max": knots[-1]},
                   "gradient": "magenta → red → orange → yellow → lime → green → teal"},
        "transparent_below": 0.0,
        "transparent_semantics": "NDVI < 0 (open water) and NoData are transparent",
        "smoothing": "normalised Gaussian on raw values, display only",
        "display_resolution_m": 20,
        "study_region_clipped": True,
        "mask_applied_after_blur": True,
    }
    rec["ndvi_statistics_in_region"] = {
        "valid_pixels": int(region_vals.size),
        "p05": float(np.percentile(region_vals, 5)), "p50": float(np.percentile(region_vals, 50)),
        "p95": float(np.percentile(region_vals, 95)), "mean": float(region_vals.mean()),
    }
    return {"metric": "ndvi", "tif": tif.name, "png": w["names"]}


def render_water_health(manifest: dict) -> dict:
    rec = manifest["surfaces"]["water_health"]
    tif = _tif_path(rec, "water-health")
    values, valid, transform, _ = read_raster(tif)
    region_vals = _in_region_values(values, valid, transform)
    knots = quantile_knots(region_vals, len(WATER_BLUE_STOPS), 2.0, 98.0)
    spec = RenderSpec(
        metric="water_health",
        stops_rgb=WATER_BLUE_STOPS,
        knot_values=knots,
        stop_labels=["lowest", "medium-low", "medium", "medium-high", "highest"],
        downsample=2, sharp_sigma=1.6, glow_sigma=5.0, halo_sigma=14.0, spread_sigma=1.2,
        sharp_alpha=240, glow_alpha=170, halo_alpha=95, min_weight=0.05,
    )
    out = render_heatmap(values, valid, transform, spec)
    stem = tif.stem
    w = _write_three(out, "water-health", stem)
    rec.update({
        "png_filename": f"water-health/{w['names']['sharp']}",
        "sharp_png_filename": f"water-health/{w['names']['sharp']}",
        "glow_png_filename": f"water-health/{w['names']['glow']}",
        "halo_png_filename": f"water-health/{w['names']['halo']}",
        "mapbox_coordinates": mapbox_coordinates_for(out["transform"], out["shape"]),
    })
    rec["files"].update({"png": w["names"]["sharp"], "sharp_png": w["names"]["sharp"],
                         "glow_png": w["names"]["glow"], "halo_png": w["names"]["halo"]})
    rec.setdefault("checksums", {}).update({
        "png_sha256": w["sums"]["sharp"], "sharp_png_sha256": w["sums"]["sharp"],
        "glow_png_sha256": w["sums"]["glow"], "halo_png_sha256": w["sums"]["halo"],
    })
    rec["display_percentiles"] = {f"p{int(p):02d}_raw": float(np.percentile(region_vals, p)) for p in (2, 5, 25, 50, 75, 95, 98)}
    rec["visualization"] = {
        "renderer": f"heatmap_render {RENDER_VERSION}",
        "layers": ["halo", "glow", "sharp"],
        "percentile_normalized": True,
        "stops": legend_stops(spec),
        "legend": {
            "left_label": f"DEGRADED · {knots[0]:.3f}",
            "right_label": f"HEALTHIER · {knots[-1]:.3f}",
            "range": {"min": knots[0], "max": knots[-1]},
            "unit": "index_0_to_1",
            "gradient": "dark teal → blue → cyan → turquoise",
            "note": "Colours stretched between in-region p2 and p98 so close values separate; raw index unchanged.",
        },
        "smoothing": "normalised Gaussian on raw values inside detected water, display only",
        "display_resolution_m": 20,
        "study_region_clipped": True,
        "mask_applied_after_blur": True,
    }
    return {"metric": "water_health", "tif": tif.name, "png": w["names"], "knots": knots}


def render_lst(manifest: dict) -> dict:
    rec = manifest["surfaces"]["lst"]
    tif = _tif_path(rec, "lst")
    values, valid, transform, _ = read_raster(tif)
    qc_valid = valid & (values >= LST_QC_MIN_C)
    region_vals = _in_region_values(values, qc_valid, transform)
    knots = quantile_knots(region_vals, len(THERMAL_STOPS), 2.0, 98.0)
    spec = RenderSpec(
        metric="lst",
        stops_rgb=THERMAL_STOPS,
        knot_values=knots,
        stop_labels=["coolest", "cool", "mild", "warm", "hot", "very hot", "hottest"],
        downsample=1, sharp_sigma=0.9, glow_sigma=3.0, halo_sigma=8.0,
        sharp_alpha=225, glow_alpha=110, halo_alpha=60,
    )
    out = render_heatmap(values, qc_valid, transform, spec)
    stem = tif.stem
    w = _write_three(out, "lst", stem)
    rec["files"].update({"png": w["names"]["sharp"], "glow_png": w["names"]["glow"], "halo_png": w["names"]["halo"]})
    rec["coordinates"] = mapbox_coordinates_for(out["transform"], out["shape"])
    rec.setdefault("checksums", {}).update({"png_sha256": w["sums"]["sharp"], "glow_png_sha256": w["sums"]["glow"],
                                            "halo_png_sha256": w["sums"]["halo"]})
    stops = legend_stops(spec)
    rec["visualization"] = {
        "renderer": f"heatmap_render {RENDER_VERSION}",
        "color_stops": [{"color": s["color"], "label": s["label"], "position": s["position"],
                         "temperature_c": round(s["value"], 1)} for s in stops],
        "qc": {"min_plausible_c": LST_QC_MIN_C,
               "rule": "pixels below this are probable residual cloud; hidden in display, excluded from cell stats"},
        "smoothing": "normalised Gaussian, display only",
        "nodata_semantics": "transparent; output alpha masked to valid pixels in the municipality union",
        "study_region_clipped": True,
        "mask_applied_after_blur": True,
    }
    rec["glow_threshold_c"] = round(knots[-2], 2)
    rec["lst_display_p02_c"], rec["lst_display_p98_c"] = round(knots[0], 2), round(knots[-1], 2)
    return {"metric": "lst", "tif": tif.name, "png": w["names"], "knots": knots}


RENDERERS = {"ndvi": render_ndvi, "water_health": render_water_health, "lst": render_lst}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=list(RENDERERS), action="append")
    args = ap.parse_args()
    manifest = _load_manifest()
    results = []
    for metric in args.only or list(RENDERERS):
        if metric not in manifest.get("surfaces", {}):
            print(f"skip {metric}: not in manifest")
            continue
        results.append(RENDERERS[metric](manifest))
        manifest["surfaces"][metric]["visualization_rendered_at"] = datetime.now(timezone.utc).isoformat()
        print(f"rendered {metric}")
    _save_manifest(manifest)
    print(json.dumps(results, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
