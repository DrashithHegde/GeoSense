"""Shared heatmap renderer for GeoSense scientific rasters.

SCIENTIFIC RASTER  ->  colour mapping  ->  visual smoothing / glow  ->  boundary mask  ->  PNG

Rules this module enforces:
  * The GeoTIFF is opened read-only and never modified. Clicks keep reading it.
  * Smoothing is a *normalised* Gaussian (blur(v*w)/blur(w)): NoData never
    contributes a value, it only lowers alpha. No value is invented where no
    valid pixel exists within a few sigma.
  * The study-region mask (Mumbai + Thane + Mira-Bhayandar union) is applied
    LAST, after blur/glow, so nothing bleeds past the municipal boundary and
    there is no rectangular footprint.
  * Legend stops always carry the RAW value each colour represents.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import rasterio
from PIL import Image
from rasterio.features import rasterize
from rasterio.transform import Affine
from scipy.ndimage import gaussian_filter

from app.services.municipality_boundaries import load_study_region_geometry

# magenta -> red -> orange -> yellow -> lime -> green -> teal/cyan
# (low / degraded  ...........................  high / healthier)
VIBRANT_STOPS: tuple[tuple[int, int, int], ...] = (
    (221, 38, 154),   # magenta
    (255, 59, 59),    # red
    (255, 140, 0),    # orange
    (255, 210, 60),   # yellow
    (150, 230, 60),   # lime
    (41, 217, 103),   # green
    (18, 200, 212),   # teal / cyan
)

# Original Water Health palette: dark teal -> blue -> cyan -> turquoise
WATER_BLUE_STOPS: tuple[tuple[int, int, int], ...] = (
    (5, 42, 58),
    (4, 82, 126),
    (0, 138, 184),
    (0, 192, 220),
    (30, 232, 238),
)

# cool -> hot, readable on a dark basemap
THERMAL_STOPS: tuple[tuple[int, int, int], ...] = (
    (37, 99, 235),    # blue
    (6, 182, 212),    # cyan
    (163, 230, 53),   # lime
    (250, 204, 21),   # yellow
    (249, 115, 22),   # orange
    (239, 68, 68),    # red
    (159, 18, 57),    # deep crimson
)


@dataclass
class RenderSpec:
    metric: str
    stops_rgb: Sequence[tuple[int, int, int]]
    knot_values: Sequence[float]          # raw value at each colour stop (monotonic)
    stop_labels: Sequence[str]
    downsample: int = 1                   # block-average factor before rendering
    sharp_sigma: float = 1.0              # in display pixels
    glow_sigma: float = 4.0
    halo_sigma: float = 10.0
    spread_sigma: float = 0.0             # >0 lets colour soften slightly past valid edges
    sharp_alpha: int = 235
    glow_alpha: int = 150
    halo_alpha: int = 90
    min_weight: float = 0.08              # below this local support the pixel is transparent
    extra: dict[str, Any] = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_raster(path: Path) -> tuple[np.ndarray, np.ndarray, Affine, tuple[float, float, float, float]]:
    """Return (values float32, valid bool, transform, bounds). Read-only."""
    with rasterio.open(path) as ds:
        values = ds.read(1).astype("float32")
        nodata = ds.nodata
        valid = np.isfinite(values)
        if nodata is not None:
            valid &= values != nodata
        b = ds.bounds
        return values, valid, ds.transform, (b.left, b.bottom, b.right, b.top)


def block_reduce_mean(values: np.ndarray, valid: np.ndarray, factor: int) -> tuple[np.ndarray, np.ndarray]:
    """NoData-aware block mean. Returns (mean, support fraction 0..1)."""
    if factor <= 1:
        return np.where(valid, values, 0.0).astype("float32"), valid.astype("float32")
    h, w = values.shape
    H, W = h // factor * factor, w // factor * factor
    v = np.where(valid, values, 0.0)[:H, :W].reshape(H // factor, factor, W // factor, factor)
    m = valid[:H, :W].reshape(H // factor, factor, W // factor, factor).astype("float32")
    s = v.sum(axis=(1, 3))
    c = m.sum(axis=(1, 3))
    mean = np.divide(s, c, out=np.zeros_like(s, dtype="float32"), where=c > 0)
    return mean.astype("float32"), (c / (factor * factor)).astype("float32")


def study_region_mask(shape: tuple[int, int], transform: Affine) -> np.ndarray:
    geom = load_study_region_geometry()
    return rasterize([(geom, 1)], out_shape=shape, transform=transform, fill=0, all_touched=False, dtype="uint8").astype(bool)


def normalized_smooth(values: np.ndarray, weight: np.ndarray, sigma: float) -> tuple[np.ndarray, np.ndarray]:
    """Normalised convolution. NoData has zero weight, so it never leaks a value."""
    if sigma <= 0:
        return values, weight
    num = gaussian_filter(values * weight, sigma, mode="constant")
    den = gaussian_filter(weight, sigma, mode="constant")
    out = np.divide(num, den, out=np.zeros_like(num), where=den > 1e-6)
    return out.astype("float32"), den.astype("float32")


def values_to_t(values: np.ndarray, knots: Sequence[float]) -> np.ndarray:
    """Piecewise-linear raw value -> 0..1 using monotonic knot values."""
    knots = np.asarray(knots, dtype="float64")
    pos = np.linspace(0.0, 1.0, len(knots))
    return np.interp(values, knots, pos).astype("float32")


def t_to_rgb(t: np.ndarray, stops_rgb: Sequence[tuple[int, int, int]]) -> np.ndarray:
    stops = np.asarray(stops_rgb, dtype="float32")
    pos = np.linspace(0.0, 1.0, len(stops))
    rgb = np.stack([np.interp(t, pos, stops[:, c]) for c in range(3)], axis=-1)
    return rgb


def _rgba(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    out = np.zeros(rgb.shape[:2] + (4,), dtype="uint8")
    out[..., :3] = np.clip(rgb, 0, 255).astype("uint8")
    out[..., 3] = np.clip(alpha, 0, 255).astype("uint8")
    return out


def _blur_rgba_premultiplied(rgb: np.ndarray, alpha01: np.ndarray, sigma: float) -> tuple[np.ndarray, np.ndarray]:
    """Gaussian blur in premultiplied space so colours don't darken at edges."""
    a = gaussian_filter(alpha01, sigma, mode="constant")
    pm = np.stack([gaussian_filter(rgb[..., c] * alpha01, sigma, mode="constant") for c in range(3)], axis=-1)
    col = np.divide(pm, a[..., None], out=np.zeros_like(pm), where=a[..., None] > 1e-6)
    return col, a


def quantile_knots(values: np.ndarray, n_stops: int, lo_pct: float = 2.0, hi_pct: float = 98.0) -> list[float]:
    """Evenly spaced percentiles between lo and hi -> colour stop raw values.

    This is a *display* stretch only (histogram-style), so that tightly clustered
    values still use the full palette. Legend reports the raw value of every stop.
    """
    pcts = np.linspace(lo_pct, hi_pct, n_stops)
    knots = np.percentile(values, pcts).astype("float64")
    # enforce strict monotonicity for np.interp
    for i in range(1, len(knots)):
        if knots[i] <= knots[i - 1]:
            knots[i] = knots[i - 1] + 1e-6
    return [float(k) for k in knots]


# ─────────────────────────────────────────────────────────────────────────────
# main entry
# ─────────────────────────────────────────────────────────────────────────────

def render_heatmap(
    values: np.ndarray,
    valid: np.ndarray,
    transform: Affine,
    spec: RenderSpec,
) -> dict[str, Any]:
    """Return {'sharp','glow','halo': RGBA uint8, 'transform', 'shape', 'region_mask'}."""
    f = max(1, int(spec.downsample))
    disp_vals, support = block_reduce_mean(values, valid, f)
    disp_transform = transform * Affine.scale(f, f)
    shape = disp_vals.shape

    region = study_region_mask(shape, disp_transform)
    weight = support * region  # only in-region valid pixels feed the colour field

    # 1) colour field from smoothed RAW values (normalised -> no NoData leakage)
    smooth_vals, smooth_w = normalized_smooth(disp_vals, weight, spec.sharp_sigma)
    t = values_to_t(smooth_vals, spec.knot_values)
    rgb = t_to_rgb(t, spec.stops_rgb)

    # 2) sharp alpha = local support (soft edges, not a hard pixel grid)
    base = np.clip((smooth_w - spec.min_weight) / max(1e-6, 1.0 - spec.min_weight), 0.0, 1.0)
    if spec.spread_sigma > 0:
        spread = gaussian_filter(weight, spec.spread_sigma, mode="constant")
        base = np.maximum(base, np.clip(spread * 2.5, 0, 1) * (smooth_w > 1e-3))
    base = np.sqrt(base)  # lift faint edges a little for vibrancy

    # extend colour field outward so blurred glow has a defined hue
    wide_vals, _ = normalized_smooth(disp_vals, weight, max(spec.glow_sigma, spec.sharp_sigma))
    wide_rgb = t_to_rgb(values_to_t(wide_vals, spec.knot_values), spec.stops_rgb)
    rgb_full = np.where(base[..., None] > 0, rgb, wide_rgb)

    # 3) glow + halo (visual only), premultiplied blur
    glow_rgb, glow_a = _blur_rgba_premultiplied(rgb_full, base, spec.glow_sigma)
    halo_rgb, halo_a = _blur_rgba_premultiplied(rgb_full, base, spec.halo_sigma)

    # 4) FINAL boundary mask (after blur) -> no bleed, no rectangle
    rm = region.astype("float32")
    sharp = _rgba(rgb_full, base * spec.sharp_alpha * rm)
    glow = _rgba(glow_rgb, np.clip(glow_a * 1.6, 0, 1) * spec.glow_alpha * rm)
    halo = _rgba(halo_rgb, np.clip(halo_a * 2.0, 0, 1) * spec.halo_alpha * rm)

    return {"sharp": sharp, "glow": glow, "halo": halo, "transform": disp_transform, "shape": shape, "region_mask": region}


def legend_stops(spec: RenderSpec) -> list[dict[str, Any]]:
    out = []
    for i, (val, rgb) in enumerate(zip(spec.knot_values, spec.stops_rgb)):
        out.append({
            "value": round(float(val), 4),
            "rgb": [int(c) for c in rgb],
            "color": "#%02x%02x%02x" % tuple(int(c) for c in rgb),
            "label": spec.stop_labels[i] if i < len(spec.stop_labels) else "",
            "position": round(i / (len(spec.stops_rgb) - 1), 4),
        })
    return out


def save_png(rgba: np.ndarray, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(path, optimize=True)
    return sha256(path)


def mapbox_coordinates_for(transform: Affine, shape: tuple[int, int]) -> list[list[float]]:
    h, w = shape
    west, north = transform * (0, 0)
    east, south = transform * (w, h)
    return [[west, north], [east, north], [east, south], [west, south]]
