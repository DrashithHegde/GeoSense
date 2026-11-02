"""Regenerate LST PNG + glow PNG from existing canonical GeoTIFF.

This script is for regenerating visualization derivatives (sharp PNG + glow PNG)
from an already-generated LST GeoTIFF without re-running the full GEE export.

Usage:
    python regenerate_lst_png.py

Finds the latest LST GeoTIFF in data/surfaces/lst/ and regenerates its PNGs.
"""
from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageFilter
import rasterio

# Add server root to path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.surfaces.lst_surface import SURFACE_ROOT, NODATA_VALUE, LST_GLOW_THRESHOLD_C

# FLIR/thermal color ramp constants (must match lst_surface.py)
STOP_V = np.array([15.0, 22.0, 26.0, 29.0, 32.0, 34.0, 36.0, 38.0, 40.0, 43.0], dtype=np.float32)
STOP_R = np.array([  0,   18,   48,   88,  138,  188,  228,  255,  255,  255 ], dtype=np.float32)
STOP_G = np.array([  0,    8,   18,   28,   38,   42,   58,   98,  168,  235 ], dtype=np.float32)
STOP_B = np.array([  0,   28,   68,  118,  128,  108,   78,   48,   88,  195 ], dtype=np.float32)
ALPHA_ZERO = np.float32(20.0)
ALPHA_FULL = np.float32(35.0)
ALPHA_MAX  = np.float32(235.0)


def lst_to_rgba(values: np.ndarray) -> np.ndarray:
    """Convert float32 LST grid to RGBA uint8 — matches lst_surface.py."""
    valid = np.isfinite(values) & (values != NODATA_VALUE)
    clamped = np.where(valid, np.clip(values, STOP_V[0], STOP_V[-1]), STOP_V[0]).ravel()
    h, w = values.shape

    r_acc = np.zeros(h * w, np.float32)
    g_acc = np.zeros(h * w, np.float32)
    b_acc = np.zeros(h * w, np.float32)

    for i in range(len(STOP_V) - 1):
        lo, hi = STOP_V[i], STOP_V[i + 1]
        seg = (clamped >= lo) & (clamped <= hi)
        t = np.where(seg, (clamped - lo) / (hi - lo), 0.0)
        r_acc += seg * (STOP_R[i] + (STOP_R[i + 1] - STOP_R[i]) * t)
        g_acc += seg * (STOP_G[i] + (STOP_G[i + 1] - STOP_G[i]) * t)
        b_acc += seg * (STOP_B[i] + (STOP_B[i + 1] - STOP_B[i]) * t)

    v_flat = values.ravel()
    alpha_f = np.where(
        v_flat < ALPHA_ZERO,
        0.0,
        np.where(
            v_flat < ALPHA_FULL,
            (((v_flat - ALPHA_ZERO) / (ALPHA_FULL - ALPHA_ZERO)).clip(0.0, 1.0) ** 1.3) * ALPHA_MAX,
            ALPHA_MAX,
        ),
    )
    alpha_f = np.where(valid.ravel(), alpha_f, 0.0)

    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[:, :, 0] = np.clip(r_acc, 0, 255).reshape(h, w).astype(np.uint8)
    rgba[:, :, 1] = np.clip(g_acc, 0, 255).reshape(h, w).astype(np.uint8)
    rgba[:, :, 2] = np.clip(b_acc, 0, 255).reshape(h, w).astype(np.uint8)
    rgba[:, :, 3] = np.clip(alpha_f, 0, 255).reshape(h, w).astype(np.uint8)
    return rgba


def main() -> int:
    lst_dir = SURFACE_ROOT / "lst"
    if not lst_dir.exists():
        print(f"ERROR: LST directory does not exist: {lst_dir}")
        return 1

    # Find latest GeoTIFF
    geotiffs = sorted(lst_dir.glob("lst_*.tif"))
    if not geotiffs:
        print(f"ERROR: No LST GeoTIFFs found in {lst_dir}")
        return 1

    geotiff_path = geotiffs[-1]
    print(f"GeoTIFF: {geotiff_path.name}")

    # Read LST data
    with rasterio.open(geotiff_path) as src:
        values = src.read(1)
        print(f"PNG    : {geotiff_path.stem}.png")

    valid_mask = np.isfinite(values) & (values != NODATA_VALUE)
    valid_count = int(np.sum(valid_mask))
    if valid_count == 0:
        print("ERROR: GeoTIFF contains zero valid pixels")
        return 1

    valid_values = values[valid_mask]
    print(f"Grid: {values.shape[1]}×{values.shape[0]}  valid: {valid_count:,}  LST [{np.min(valid_values):.3f}, {np.max(valid_values):.3f}]  mean {np.mean(valid_values):.3f}")

    # Generate sharp PNG
    print("Rendering sharp PNG …")
    rgba = lst_to_rgba(values)
    sharp_png = lst_dir / f"{geotiff_path.stem}.png"
    Image.fromarray(rgba, mode="RGBA").save(sharp_png, "PNG", compress_level=6)
    sharp_size_mb = sharp_png.stat().st_size / (1024 * 1024)
    print(f"Saved sharp PNG: {sharp_size_mb:.2f} MB")

    # Generate glow PNG
    print(f"Rendering glow PNG (threshold: {LST_GLOW_THRESHOLD_C}°C) …")
    hot_mask = valid_mask & (values >= LST_GLOW_THRESHOLD_C)
    glow_values = np.where(hot_mask, values, np.nan)
    glow_rgba = lst_to_rgba(np.nan_to_num(glow_values, nan=NODATA_VALUE))

    # Apply Gaussian blur
    img = Image.fromarray(glow_rgba, mode="RGBA")
    r, g, b, a = img.split()
    r_blur = r.filter(ImageFilter.GaussianBlur(radius=3.0))
    g_blur = g.filter(ImageFilter.GaussianBlur(radius=3.0))
    b_blur = b.filter(ImageFilter.GaussianBlur(radius=3.0))
    glow_img = Image.merge("RGBA", (r_blur, g_blur, b_blur, a))

    glow_png = lst_dir / f"{geotiff_path.stem}_glow.png"
    glow_img.save(glow_png, "PNG", compress_level=6)
    glow_size_mb = glow_png.stat().st_size / (1024 * 1024)
    print(f"Saved glow PNG: {glow_size_mb:.2f} MB")

    print("Done — GeoTIFF and LST values unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
