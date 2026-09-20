"""Canonical backend Composite score used by the existing Composite view contract."""
from __future__ import annotations

from typing import Any


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def normalize_aqi(aqi: float | None) -> float | None:
    if aqi is None:
        return None
    return _clamp(float(aqi) / 5.0)


def normalize_ndvi(ndvi: float | None) -> float | None:
    if ndvi is None:
        return None
    # Lower vegetation is a higher stress contribution.
    return _clamp((0.8 - float(ndvi)) / 1.0 * 100.0)


def normalize_lst(lst: float | None) -> float | None:
    if lst is None:
        return None
    return _clamp((float(lst) - 20.0) / 30.0 * 100.0)


def normalize_water_health(water_health_score: float | None) -> float | None:
    if water_health_score is None:
        return None
    # Water Health is stored as condition (higher is healthier), so Composite
    # risk uses its inverse. NULL means not applicable, never zero risk.
    return _clamp((1.0 - float(water_health_score)) * 100.0)


def calculate_composite(
    *,
    aqi: float | None,
    ndvi: float | None,
    lst: float | None,
    water_health_score: float | None,
    anomaly_score: float | None = None,
) -> dict[str, Any]:
    """Combine available environmental stress components with explicit weighting.

    The weights are equal among available components. Missing values are excluded
    from both numerator and denominator, and the result is unavailable when no
    component exists. The returned score is 0..100 environmental stress, where
    0 is better and 100 is worse. Water Health contributes only where detected
    water exists.
    """
    normalized = {
        "aqi": normalize_aqi(aqi),
        "ndvi": normalize_ndvi(ndvi),
        "lst": normalize_lst(lst),
        "water_health": normalize_water_health(water_health_score),
    }
    available = {name: value for name, value in normalized.items() if value is not None}
    contributions = {name: (value / len(available) if available else None) for name, value in available.items()}
    score = sum(contributions.values()) if contributions else None

    return {
        "score": round(float(score), 4) if score is not None else None,
        "status": "unavailable" if score is None else "elevated" if score >= 70 else "moderate" if score >= 50 else "lower",
        "weights": {name: round(1.0 / len(available), 4) for name in available},
        "normalized_components": normalized,
        "contributions": {name: round(value, 4) for name, value in contributions.items()},
        "available_components": list(available),
        "missing_components": [name for name, value in normalized.items() if value is None],
        "anomaly_score": anomaly_score,
        "interpretation": "0 is lower environmental stress and 100 is higher environmental stress; contributions are statistical, not causal",
    }