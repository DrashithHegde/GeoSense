"""Shared heatmap renderer for GeoSense scientific rasters.

SCIENTIFIC RASTER  ->  colour mapping  ->  visual smoothing / glow  ->  boundary mask  ->  PNG

Rules this module enforces:
  * The GeoTIFF is opened read-only and never modified. Clicks keep reading it.
  * Smoothing is a *normalised* Gaussian (blur(v*w)/blur(w)): NoData never
    contributes a value, it only lowers alpha. No value is invented where no
    valid pixel exists within a few sigma.
  * The study-region mask (union of the city's municipalities) is applied
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

# LST: perceptual "plasma"-style thermal scale for a dark basemap — cool surfaces recede
# (indigo/purple), hot surfaces glow (orange → yellow). No greens/blues, so it is never
# confused with vegetation or water.
THERMAL_STOPS: tuple[tuple[int, int, int], ...] = (
    (52, 38, 150),    # indigo      — coolest
    (98, 30, 162),    # purple
    (152, 34, 150),   # violet-magenta
    (206, 58, 112),   # rose-red
    (238, 101, 72),   # red-orange
    (250, 157, 52),   # orange
    (253, 222, 94),   # warm yellow — hottest
)

# NDVI: earth → green. No vegetation (built-up / bare) is brown, sparse is tan → yellow,
# moderate is light green, dense forest / mangrove is deep green.
NDVI_STOPS: tuple[tuple[int, int, int], ...] = (
    (86, 66, 52),     # bare / built-up (dark brown, recedes)
    (128, 94, 62),    # very sparse (brown)
    (176, 140, 76),   # sparse (tan)
    (218, 200, 96),   # light vegetation (sand-yellow)
    (150, 208, 76),   # moderate vegetation (yellow-green / light green)
    (60, 188, 84),    # dense vegetation (green)
    (24, 150, 78),    # very dense: forest / mangrove (deep green)
)

# Composite stress: calm teal (low) → yellow → orange → red → crimson (critical).
STRESS_STOPS: tuple[tuple[int, int, int], ...] = (
    (32, 92, 120),    # very low
    (38, 140, 138),   # low
    (110, 170, 120),  # mild
    (214, 196, 92),   # moderate
    (244, 144, 62),   # elevated
    (226, 70, 60),    # high
    (176, 30, 96),    # very high
)

# CPCB National AQI category colours: the official hues (green, light green, yellow, orange,
# red, maroon), brightened so they glow on a dark map. The map and the legend use exactly these.
AQI_CPCB_STOPS: tuple[tuple[int, int, int], ...] = (
    (0, 224, 122),    # Good          0-50
    (168, 232, 72),   # Satisfactory 51-100
    (255, 236, 64),   # Moderate    101-200
    (255, 158, 40),   # Poor        201-300
    (255, 66, 66),    # Very Poor   301-400
    (214, 36, 82),    # Severe      401-500
)
AQI_BANDS = (("Good", 0, 50), ("Satisfactory", 51, 100), ("Moderate", 101, 200), ("Poor", 201, 300),
             ("Very Poor", 301, 400), ("Severe", 401, 500))
AQI_KNOTS = [25, 75, 150, 250, 350, 450]     # CPCB category midpoints: colours blend smoothly between them


def aqi_band_colours() -> dict[str, Any]:
    """Smooth AQI gradient (green -> yellow -> orange -> red): each CPCB colour sits at its
    category midpoint and the colours blend continuously in between."""
    return {"stops_rgb": AQI_CPCB_STOPS, "knot_values": list(AQI_KNOTS),
            "stop_labels": [name for name, _, _ in AQI_BANDS]}


@dataclass
class RenderSpec:
    metric: str
    stops_rgb: Sequence[tuple[int, int, int]]
    knot_values: Sequence[float]          # raw value at each colour stop (monotonic)
    stop_labels: Sequence[str]
    downsample: int = 1                   # block-average factor before rendering
    upsample: int = 1                     # bilinear display upsampling for coarse grids (AQI)
    sharp_sigma: float = 1.0              # in display pixels
    glow_sigma: float = 4.0
    halo_sigma: float = 10.0
    spread_sigma: float = 0.0             # >0 lets colour soften slightly past valid edges
    sharp_alpha: int = 235
    glow_alpha: int = 150
    halo_alpha: int = 90
    min_weight: float = 0.08              # below this local support the pixel is transparent
    relief: float = 0.0                   # relief shading strength (0 = flat); display only
    relief_sigma: float = 2.5             # smoothing of the shaded "height" field, display px
    relief_z: float = 60.0                # vertical exaggeration of that height field
    glow_by_value: float = 0.0            # >0: thermal-camera bloom — glow comes mostly from high
                                          # values (weight t**this), calm areas barely glow
    glow_reach_px: float | None = None    # glow/halo only within this distance of real pixels
                                          # (None = unlimited). Keeps no-data holes visibly empty.
    glow_gain: float = 1.0                # >1 brightens the glow/halo colour (same hue) so darker
                                          # palette ends still read as light; sharp colours unchanged
    bloom: float = 0.0                    # >0: inner glow - high values shine onto lower neighbours.
                                          # In a continuous field (NDVI, Composite) the glow/halo images
                                          # are hidden under the top image except at edges.
    bloom_sigma: float = 4.0              # reach of that light, display px
    bloom_power: float = 1.5              # which values emit light: t**power (high values glow most)
    extra: dict[str, Any] = field(default_factory=dict)


# One look for every layer, matched to Water Health's glow (strong glow + wide halo), plus
# relief shading so high values read as raised and low values as sunken (like a terrain map).
# DISPLAY ONLY: colours still map to the same values and legend; the GeoTIFF is untouched.
GLOW_STYLE = dict(glow_sigma=5.0, halo_sigma=14.0, sharp_alpha=240, glow_alpha=170, halo_alpha=95)
RELIEF = dict(relief=0.38, relief_sigma=4.0, relief_z=45.0, glow_reach_px=3.0)
# the settings LST's map images were rendered with (the look you approved)
LST_LOOK = dict(sharp_sigma=0.9, glow_sigma=3.0, halo_sigma=8.0, sharp_alpha=225, glow_alpha=110, halo_alpha=60)
LAYER_STYLE: dict[str, dict[str, Any]] = {
    "water_health": dict(GLOW_STYLE, sharp_sigma=1.6, spread_sigma=1.2, min_weight=0.05),  # unchanged look
    # NDVI: LST's settings at LST's 30 m display scale (render_ndvi uses downsample=3), no relief.
    # NDVI is a continuous field, so its glow/halo images only show at edges; the inner glow
    # (bloom) lets green areas shine softly onto the built-up land around them, the way LST hot
    # spots glow. NDVI colours are unchanged (brown -> yellow -> light green -> dark green).
    "ndvi": dict(LST_LOOK, sharp_sigma=1.2, glow_alpha=150, halo_alpha=90, glow_by_value=0.8,
                 glow_gain=1.4, bloom=0.45, bloom_sigma=4.0, bloom_power=1.5),
    "lst": dict(GLOW_STYLE, sharp_sigma=0.9, **RELIEF),
    # AQI is a smooth interpolated field: no relief (it turns station circles into bubbles);
    # upsampled ×4 so the coastline and the glow are smooth instead of 270 m steps.
    "aqi": dict(GLOW_STYLE, sharp_sigma=2.0, upsample=4, glow_reach_px=None),
    # Composite: LST look + thermal-camera bloom (high stress glows, calm areas do not); softer
    # colour field and an inner glow from high-stress areas onto their surroundings.
    "composite": dict(LST_LOOK, sharp_sigma=1.6, glow_alpha=210, halo_alpha=130, glow_sigma=4.0, halo_sigma=11.0,
                      glow_by_value=1.4, glow_gain=1.3, bloom=0.45, bloom_sigma=4.0, bloom_power=2.0),
}


def layer_style(metric: str) -> dict[str, Any]:
    return dict(LAYER_STYLE.get(metric, GLOW_STYLE))


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


def relief_shade(rgb: np.ndarray, t: np.ndarray, support: np.ndarray, strength: float,
                 sigma: float = 2.5, z: float = 60.0, azimuth_deg: float = 315.0, altitude_deg: float = 45.0) -> np.ndarray:
    """Hillshade the colour field using the colour position t (0..1) as a height.

    Light from the north-west at 45 degrees (the cartographic convention). Lit slopes get
    brighter, shadowed slopes darker, flat areas keep their colour exactly, so hue — and therefore
    the value a colour stands for — is unchanged. Display only.
    """
    h_raw = np.where(support > 0, np.nan_to_num(t, nan=0.0), 0.0).astype("float32")
    w = (support > 0).astype("float32")
    num = gaussian_filter(h_raw * w, sigma, mode="nearest")
    den = gaussian_filter(w, sigma, mode="nearest")
    h = np.divide(num, den, out=np.zeros_like(num), where=den > 1e-6) * z
    dy, dx = np.gradient(h)
    slope = np.arctan(np.hypot(dx, dy))
    aspect = np.arctan2(-dx, dy)
    zen = np.radians(90.0 - altitude_deg)
    az = np.radians(360.0 - azimuth_deg + 90.0)
    shade = np.cos(zen) * np.cos(slope) + np.sin(zen) * np.sin(slope) * np.cos(az - aspect)
    factor = np.clip(shade / np.cos(zen), 0.0, 2.0)          # 1.0 on flat ground
    gain = 1.0 + strength * (factor - 1.0)
    out = rgb.astype("float32") * gain[..., None]
    # a little white on the brightest lit slopes reads as a soft highlight (glossy, 3-D)
    hi = np.clip((factor - 1.2) / 0.6, 0.0, 1.0)[..., None] * strength * 40.0
    return np.clip(out + hi, 0, 255)


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

def station_fade(shape: tuple[int, int], transform: Affine, stations: Sequence[dict],
                 sigma_m: float = 3000.0, floor: float = 0.25) -> np.ndarray | None:
    """Brightness by closeness to monitoring stations (display only).

    Each station contributes a smooth Gaussian "support" (sigma ~3 km); the sum, capped at 1,
    sets brightness between `floor` (far from every station) and 1 (at or between nearby
    stations). Smooth by construction — no seams between stations. The interpolated value is
    unchanged; far from stations it is only shown dimmer, because there it is an estimate
    (see the leave-one-station-out error)."""
    pts = [(float(s["lat"]), float(s["lon"])) for s in stations or [] if s.get("lat") is not None and s.get("lon") is not None]
    if not pts:
        return None
    h, w = shape
    lon = transform.c + (np.arange(w) + 0.5) * transform.a
    lat = transform.f + (np.arange(h) + 0.5) * transform.e
    LON, LAT = np.meshgrid(lon, lat)
    k = np.cos(np.radians(np.mean([p[0] for p in pts])))
    support = np.zeros(shape, dtype="float64")
    for la, lo in pts:
        d2 = (111_320.0 ** 2) * ((LAT - la) ** 2 + ((LON - lo) * k) ** 2)
        support += np.exp(-d2 / (2.0 * sigma_m ** 2))
    return (floor + (1.0 - floor) * np.clip(support, 0.0, 1.0)).astype("float32")


def render_heatmap(
    values: np.ndarray,
    valid: np.ndarray,
    transform: Affine,
    spec: RenderSpec,
    alpha_scale_fn=None,
) -> dict[str, Any]:
    """Return {'sharp','glow','halo': RGBA uint8, 'transform', 'shape', 'region_mask'}.

    alpha_scale_fn(shape, display_transform) -> array 0..1 optionally dims the display layers
    (e.g. AQI brightness by distance to stations). Values and colours are not changed."""
    u = max(1, int(spec.upsample))
    if u > 1:
        # display-only bilinear upsampling of a coarse grid (values between grid points are the
        # linear blend of their neighbours; nothing is added outside valid pixels)
        from scipy.ndimage import zoom
        filled = np.where(valid, values, 0.0).astype("float32")
        w0 = valid.astype("float32")
        num = zoom(filled, u, order=1)
        den = zoom(w0, u, order=1)
        values = np.divide(num, den, out=np.zeros_like(num), where=den > 1e-6).astype("float32")
        valid = den > 0.5
        transform = transform * Affine.scale(1.0 / u, 1.0 / u)
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
    if spec.relief > 0:
        rgb_full = relief_shade(rgb_full, t, base, spec.relief, spec.relief_sigma, spec.relief_z)

    if spec.bloom > 0:
        # Inner glow (display only): high values shine a soft light onto lower-value neighbours,
        # like the glow around LST hot spots or Water Health's water lines. A uniform area keeps
        # its own colour (nothing brighter nearby); a park glows into the built-up area around it.
        # The light is the high values' own colour, brightened by glow_gain - same hues.
        tt = np.clip(np.nan_to_num(t, nan=0.0), 0.0, 1.0)
        emit = base * tt ** spec.bloom_power
        b_rgb, b_a = _blur_rgba_premultiplied(rgb_full, emit, spec.bloom_sigma)
        local = gaussian_filter(base, spec.bloom_sigma, mode="constant")
        e = np.divide(b_a, local, out=np.zeros_like(b_a), where=local > 1e-6)
        spill = np.clip((e - tt ** spec.bloom_power) * spec.bloom * 2.0, 0.0, spec.bloom)[..., None]
        light = np.clip(b_rgb * spec.glow_gain, 0, 255)
        rgb_full = rgb_full * (1.0 - spill) + light * spill

    # 3) glow + halo (visual only), premultiplied blur
    glow_src = base
    if spec.glow_by_value > 0:
        # FLIR-style: hot (high-value) areas bloom, low values add almost no glow. Colours unchanged.
        glow_src = base * np.clip(np.nan_to_num(t, nan=0.0), 0.0, 1.0) ** spec.glow_by_value
    glow_rgb, glow_a = _blur_rgba_premultiplied(rgb_full, glow_src, spec.glow_sigma)
    halo_rgb, halo_a = _blur_rgba_premultiplied(rgb_full, glow_src, spec.halo_sigma)
    if spec.glow_gain != 1.0:
        glow_rgb = np.clip(glow_rgb * spec.glow_gain, 0, 255)
        halo_rgb = np.clip(halo_rgb * spec.glow_gain, 0, 255)

    # 4) FINAL boundary mask (after blur) -> no bleed, no rectangle
    rm = region.astype("float32")
    if alpha_scale_fn is not None:
        scale = alpha_scale_fn(shape, disp_transform)
        if scale is not None:
            rm = rm * scale
    if spec.glow_reach_px:
        # glow may spill a few pixels past real data (the soft 3-D edge) but never fills a
        # no-data hole (cloud gap): those must stay visibly empty.
        from scipy.ndimage import distance_transform_edt
        reach = distance_transform_edt(base <= 0.02)
        near = np.clip(1.0 - (reach - 1.0) / spec.glow_reach_px, 0.0, 1.0).astype("float32")
        glow_a = glow_a * near
        halo_a = halo_a * near
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


def save_layers(out: dict[str, Any], out_dir: Path, stem: str, fmt: str | None = None) -> tuple[dict[str, str], dict[str, str]]:
    """Write the three display layers as WebP (much smaller than PNG, same look).

    sharp: full resolution, high-quality lossy (average colour difference ~3/255, invisible; about
    a third of the lossless size). glow/halo: half resolution — they are heavily blurred, so the
    smaller size is invisible; Mapbox stretches them to the same corners.
    Returns (file names, sha256 sums).
    """
    import os
    fmt = (fmt or os.getenv("HEATMAP_FORMAT", "png")).lower()
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = "png" if fmt == "png" else "webp"
    names = {k: f"{stem}_{k}.{ext}" for k in ("sharp", "glow", "halo")}
    sums: dict[str, str] = {}
    for k, name in names.items():
        img = Image.fromarray(out[k], mode="RGBA")
        path = out_dir / name
        if ext == "png":
            # PNG fallback (larger files, decodes everywhere); glow/halo still half size
            if k != "sharp":
                img = img.resize((max(1, img.width // 2), max(1, img.height // 2)), Image.BILINEAR)
            img.save(path, format="PNG", optimize=True)
        elif k == "sharp":
            img.save(path, format="WEBP", quality=94, alpha_quality=100, method=4)
        else:
            img = img.resize((max(1, img.width // 2), max(1, img.height // 2)), Image.BILINEAR)
            img.save(path, format="WEBP", quality=82, alpha_quality=90, method=4)
        sums[k] = sha256(path)
    return names, sums


def mapbox_coordinates_for(transform: Affine, shape: tuple[int, int]) -> list[list[float]]:
    h, w = shape
    west, north = transform * (0, 0)
    east, south = transform * (w, h)
    return [[west, north], [east, north], [east, south], [west, south]]