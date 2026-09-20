"""
Regenerate the NDVI visualization PNG from the existing GeoTIFF.
Fully vectorised — runs in a few seconds on 2005x3675.

Does NOT touch the GeoTIFF, database, API, or NDVI values.
Run inside the server container:  python /app/regenerate_ndvi_png.py
"""
from __future__ import annotations
import hashlib, json, os, sys
from pathlib import Path

_PROJ = Path(sys.prefix) / "Lib" / "site-packages" / "rasterio" / "proj_data"
if _PROJ.is_dir():
    os.environ["PROJ_LIB"] = str(_PROJ)
    os.environ["PROJ_DATA"] = str(_PROJ)

import numpy as np
import rasterio
from PIL import Image

SERVER_ROOT  = Path(__file__).resolve().parent
SURFACE_ROOT = SERVER_ROOT / "data" / "surfaces"
NDVI_ROOT    = SURFACE_ROOT / "ndvi"
MANIFEST     = SURFACE_ROOT / "manifest.json"
NODATA_VALUE = -9999.0

# ── Colour + alpha ramp (must stay in sync with ndvi_surface.py) ─────────────
#   stop_v: NDVI thresholds
#   stop_r/g/b: RGB at each threshold (interpolated continuously between stops)
#   Alpha: 0 below -0.05, linear ramp to 220 at 0.18, plateau at 220 above
STOP_V = np.array([ 0.00,  0.10,  0.20,  0.30,  0.42,  0.55,  0.68,  0.80], dtype=np.float32)
STOP_R = np.array([ 40,    58,    72,    65,    48,    30,    16,     5  ], dtype=np.float32)
STOP_G = np.array([ 48,    72,   100,   130,   158,   175,   190,   205  ], dtype=np.float32)
STOP_B = np.array([ 30,    28,    32,    35,    42,    50,    58,    65  ], dtype=np.float32)
ALPHA_ZERO = np.float32( 0.05)
ALPHA_FULL = np.float32( 0.35)
ALPHA_MAX  = np.float32( 210.0)


def ndvi_to_rgba(values: np.ndarray) -> np.ndarray:
    """Vectorised NDVI → RGBA.  NoData / non-finite → alpha 0."""
    valid  = np.isfinite(values) & (values != NODATA_VALUE)
    clamped = np.where(valid, np.clip(values, STOP_V[0], STOP_V[-1]),
                       np.float32(STOP_V[0])).ravel()
    h, w = values.shape

    r_acc = np.zeros(h * w, np.float32)
    g_acc = np.zeros(h * w, np.float32)
    b_acc = np.zeros(h * w, np.float32)

    for i in range(len(STOP_V) - 1):
        lo, hi = STOP_V[i], STOP_V[i + 1]
        seg = (clamped >= lo) & (clamped <= hi)
        t   = np.where(seg, (clamped - lo) / (hi - lo), 0.0)
        r_acc += seg * (STOP_R[i] + (STOP_R[i+1] - STOP_R[i]) * t)
        g_acc += seg * (STOP_G[i] + (STOP_G[i+1] - STOP_G[i]) * t)
        b_acc += seg * (STOP_B[i] + (STOP_B[i+1] - STOP_B[i]) * t)

    v_flat = values.ravel()
    alpha_f = np.where(
        v_flat < ALPHA_ZERO,
        0.0,
        np.where(
            v_flat < ALPHA_FULL,
            (((v_flat - ALPHA_ZERO) / (ALPHA_FULL - ALPHA_ZERO)).clip(0.0, 1.0) ** 1.6) * ALPHA_MAX,
            ALPHA_MAX,
        ),
    )
    alpha_f = np.where(valid.ravel(), alpha_f, 0.0)

    rgba = np.zeros((h, w, 4), np.uint8)
    rgba[:, :, 0] = np.clip(r_acc, 0, 255).reshape(h, w).astype(np.uint8)
    rgba[:, :, 1] = np.clip(g_acc, 0, 255).reshape(h, w).astype(np.uint8)
    rgba[:, :, 2] = np.clip(b_acc, 0, 255).reshape(h, w).astype(np.uint8)
    rgba[:, :, 3] = np.clip(alpha_f, 0, 255).reshape(h, w).astype(np.uint8)
    return rgba


def sha256(path: Path) -> str:
    d = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            d.update(block)
    return d.hexdigest()


def main() -> None:
    tif_files = sorted(NDVI_ROOT.glob("ndvi_*.tif"))
    if not tif_files:
        print("ERROR: no ndvi_*.tif in", NDVI_ROOT); sys.exit(1)
    tif_path = tif_files[-1]
    png_path = tif_path.with_suffix(".png")
    print("GeoTIFF:", tif_path.name)
    print("PNG    :", png_path.name)

    with rasterio.open(tif_path) as src:
        values = src.read(1).astype(np.float32)
        nodata = src.nodata
    if nodata is not None:
        values[values == nodata] = NODATA_VALUE

    h, w = values.shape
    valid = np.isfinite(values) & (values != NODATA_VALUE)
    vv = values[valid]
    print(f"Grid: {w}×{h}  valid: {valid.sum():,}  "
          f"NDVI [{vv.min():.3f}, {vv.max():.3f}]  mean {vv.mean():.3f}")

    print("Rendering …")
    rgba = ndvi_to_rgba(values)

    a = rgba[:, :, 3][valid]
    print(f"Alpha distribution — zero: {(a==0).sum():,}  "
          f"partial: {((a>0)&(a<220)).sum():,}  "
          f"opaque(≥220): {(a>=220).sum():,}")

    print("Saving PNG …")
    Image.fromarray(rgba, mode="RGBA").save(png_path)
    size_mb = png_path.stat().st_size / 1024 / 1024
    print(f"Saved {size_mb:.2f} MB")

    if MANIFEST.exists():
        m = json.loads(MANIFEST.read_text(encoding="utf-8"))
        rec = m.get("surfaces", {}).get("ndvi")
        if rec:
            rec["checksums"]["png_sha256"] = sha256(png_path)
            tmp = MANIFEST.with_suffix(".tmp")
            tmp.write_text(json.dumps(m, indent=2, sort_keys=True), encoding="utf-8")
            tmp.replace(MANIFEST)
            print("Manifest checksum updated.")

    print("Done — GeoTIFF and NDVI values unchanged.")


if __name__ == "__main__":
    main()
