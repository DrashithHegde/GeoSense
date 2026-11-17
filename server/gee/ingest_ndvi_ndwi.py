"""Sentinel-2 building blocks shared by the NDVI, Water Health, index and history layers.

* S2_DATASET, the 14-day composite window and the MNDWI water threshold
* mask_s2_sr (QA60 cloud + cirrus mask) and add_indices (NDVI, NDWI, MNDWI, NDCI proxy,
  turbidity proxy) for Earth Engine images
* source_context: the provenance record of a composite window
* plain-number versions of the water indices and the Water Health score (used in tests and
  to document the formula)

The layers themselves are built by app/services/surfaces/*_surface.py (GeoTIFF -> map), and the
300 m cell values by app/services/ml/cell_features.py.
"""
from __future__ import annotations

from datetime import datetime

import ee

S2_DATASET = "COPERNICUS/S2_SR_HARMONIZED"
COMPOSITE_WINDOW_DAYS = 14
DEFAULT_MNDWI_THRESHOLD = 0.15


def calculate_mndwi(green: float | None, shortwave_ir: float | None) -> float | None:
    """MNDWI = (B3 - B11) / (B3 + B11)."""
    if green is None or shortwave_ir is None:
        return None
    denominator = green + shortwave_ir
    if denominator == 0:
        return None
    return float((green - shortwave_ir) / denominator)


def water_health_applicable(mndwi: float | None, threshold: float = DEFAULT_MNDWI_THRESHOLD) -> bool:
    """True only when a location is detected as water under the configured MNDWI threshold."""
    return mndwi is not None and mndwi >= threshold


def calculate_ndci_proxy(red_edge: float | None, red: float | None) -> float | None:
    """Sentinel-2 algal/chlorophyll-related spectral proxy: (B5 - B4) / (B5 + B4)."""
    if red_edge is None or red is None:
        return None
    denominator = red_edge + red
    if denominator == 0:
        return None
    return float((red_edge - red) / denominator)


def calculate_turbidity_proxy(green: float | None, red: float | None) -> float | None:
    """Relative suspended-material proxy based on green/red contrast, not NTU."""
    if green is None or red is None:
        return None
    denominator = green + red
    if denominator == 0:
        return None
    return float((green - red) / denominator)


def calculate_water_health_score(
    *,
    mndwi: float | None,
    ndci: float | None,
    turbidity_proxy: float | None,
    prior_change_pct: float | None,
    anomaly_score: float | None,
    water_threshold: float = DEFAULT_MNDWI_THRESHOLD,
) -> float | None:
    """Explainable Water Health score for detected water only.

    The score is a 0..1 condition score where higher means better condition. It is
    a relative early-warning indicator and intentionally does not treat more water
    as automatically healthier. Missing values remain missing.
    """
    if not water_health_applicable(mndwi, threshold=water_threshold):
        return None

    if all(value is None for value in (ndci, turbidity_proxy, prior_change_pct, anomaly_score)):
        return None

    health_components: list[float] = []
    if ndci is not None:
        algal_stress = max(0.0, min(1.0, (ndci + 1.0) / 2.0))
        health_components.append(1.0 - algal_stress)
    if turbidity_proxy is not None:
        suspended_material_stress = max(0.0, min(1.0, (turbidity_proxy + 1.0) / 2.0))
        health_components.append(1.0 - suspended_material_stress)
    if prior_change_pct is not None:
        deterioration_stress = max(0.0, min(1.0, abs(min(0.0, prior_change_pct))))
        health_components.append(1.0 - deterioration_stress)
    if anomaly_score is not None:
        health_components.append(1.0 - max(0.0, min(1.0, anomaly_score)))

    if not health_components:
        return None
    return float(max(0.0, min(1.0, sum(health_components) / len(health_components))))


def mask_s2_sr(image: ee.Image) -> ee.Image:
    # QA60 cloud mask: bits 10 (cloud) and 11 (cirrus)
    qa = image.select("QA60")
    cloudBitMask = 1 << 10
    cirrusBitMask = 1 << 11
    mask = qa.bitwiseAnd(cloudBitMask).eq(0).And(qa.bitwiseAnd(cirrusBitMask).eq(0))
    return image.updateMask(mask)


def add_indices(image: ee.Image) -> ee.Image:
    # Sentinel-2 bands: B3=green, B4=red, B5=red-edge, B8=NIR, B11=SWIR
    ndvi = image.normalizedDifference(["B8", "B4"]).rename("NDVI")
    ndwi = image.normalizedDifference(["B3", "B8"]).rename("NDWI")
    mndwi = image.normalizedDifference(["B3", "B11"]).rename("MNDWI")
    ndci = image.normalizedDifference(["B5", "B4"]).rename("NDCI_PROXY")
    turbidity = image.normalizedDifference(["B3", "B4"]).rename("TURBIDITY_PROXY")
    return image.addBands([ndvi, ndwi, mndwi, ndci, turbidity])


def source_context(start_date: str, end_date: str) -> dict:
    start = datetime.fromisoformat(start_date).date()
    end = datetime.fromisoformat(end_date).date()
    if (end - start).days != COMPOSITE_WINDOW_DAYS:
        raise ValueError(
            f"NDVI/NDWI history uses a fixed {COMPOSITE_WINDOW_DAYS}-day composite window; "
            f"received {start_date} to {end_date}"
        )
    return {
        "dataset": S2_DATASET,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "window_days": COMPOSITE_WINDOW_DAYS,
        "composite": "median",
        "scale_m": 10,
        "cloud_mask": "project-established QA60-cloud filtering with cirrus exclusion",
        "indices": {
            "ndvi": "normalizedDifference(B8,B4)",
            "ndwi": "normalizedDifference(B3,B8)",
            "mndwi": "normalizedDifference(B3,B11)",
            "ndci_proxy": "normalizedDifference(B5,B4)",
            "turbidity_proxy": "normalizedDifference(B3,B4)",
        },
        "mndwi_threshold": DEFAULT_MNDWI_THRESHOLD,
    }
