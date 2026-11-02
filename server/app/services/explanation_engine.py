"""Deterministic, evidence-grounded explanation engine for GeoSense.

This module generates human-readable environmental explanations from a
pre-validated evidence object produced by explanation_evidence.py.

Strict rules:
- Every factual sentence must trace back to a field in the evidence object.
- If a value is None / unavailable, the explanation says so explicitly.
- The engine never invents, infers, or interpolates missing data.
- Causal language ("caused by", "because of", "the reason is") is forbidden
  unless the underlying evidence explicitly supports the claim.
- Statistical deviations are described as "dominant deviation" or "strongest
  model contributor", never as physical cause.
"""
from __future__ import annotations

from typing import Any


# ──────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────

_METRIC_LABELS: dict[str, str] = {
    "aqi":  "AQI (Air Quality Index)",
    "lst":  "LST (Land Surface Temperature)",
    "ndvi": "NDVI (Vegetation Index)",
    "ndwi": "NDWI (Water Index)",
}

_AQI_CATEGORY: list[tuple[int, str]] = [
    (50,  "Good"),
    (100, "Satisfactory"),
    (200, "Moderate"),
    (300, "Poor"),
    (400, "Very Poor"),
    (500, "Severe"),
]


def _aqi_category(value: int | None) -> str:
    if value is None:
        return "unknown"
    for threshold, label in _AQI_CATEGORY:
        if value <= threshold:
            return label
    return "Severe"


def _fmt_float(value: float | None, decimals: int = 2, unit: str = "") -> str:
    if value is None:
        return "unavailable"
    formatted = f"{value:.{decimals}f}"
    return f"{formatted} {unit}".strip() if unit else formatted


def _sigma(z: float | None) -> str:
    if z is None:
        return "σ unavailable"
    sign = "+" if z >= 0 else ""
    return f"{sign}{z:.2f}σ"


def _direction_word(z: float | None) -> str:
    if z is None:
        return "different"
    return "above" if z >= 0 else "below"


# ──────────────────────────────────────────────────────────────
# Section builders
# ──────────────────────────────────────────────────────────────

def _classification_sentence(evidence: dict[str, Any]) -> str:
    iso = evidence["isolation_forest"]
    zone = evidence["zone"]
    date = evidence.get("analysis_timestamp", "unknown date")
    zone_name = zone.get("name", f"Zone {zone['id']}")

    if iso["is_anomaly"]:
        score = _fmt_float(iso["anomaly_score"])
        return (
            f"{zone_name} is classified as a SPATIAL ANOMALY in the "
            f"{date[:10]} Isolation Forest snapshot "
            f"(anomaly score: {score}, higher = more isolated)."
        )
    else:
        return (
            f"{zone_name} is classified as a SPATIAL INLIER in the "
            f"{date[:10]} Isolation Forest snapshot — "
            f"its environmental measurements are not unusually different from the Mumbai snapshot distribution."
        )


def _dominant_deviations_paragraph(evidence: dict[str, Any]) -> str:
    deviations = evidence["isolation_forest"].get("dominant_deviations") or []
    if not deviations:
        return (
            "No dominant deviation data is available in the stored evidence. "
            "This may occur when the zone was excluded from the Isolation Forest cohort."
        )
    lines = ["The strongest model contributors (dominant deviations from the spatial distribution):"]
    for item in deviations:
        var = item.get("variable", "?").upper()
        z = item.get("z_score")
        direction = item.get("direction", "different")
        value = item.get("value")
        label_str = f"value: {_fmt_float(value)}" if value is not None else "value: unavailable"
        lines.append(
            f"  • {var}: {_sigma(z)} {direction} the Mumbai spatial baseline ({label_str})."
        )
    lines.append(
        "\nNote: These are statistical deviations identified by the model, "
        "not claims of physical causation."
    )
    return "\n".join(lines)


def _measurements_paragraph(evidence: dict[str, Any]) -> str:
    m = evidence["measurements"]
    prov = evidence["provenance"]
    aqi_src = prov["aqi"]["source_type"]
    dist = prov["aqi"].get("nearest_station_distance_m")

    if aqi_src == "observed":
        aqi_prov_str = "directly observed at a monitoring station"
    elif aqi_src == "estimated":
        dist_str = f"{dist:.0f} m away" if dist is not None else "unknown distance"
        aqi_prov_str = f"IDW-estimated (nearest station {dist_str}) — not a direct observation"
    else:
        aqi_prov_str = "provenance unknown"

    lines = ["Current measurements:"]
    aqi_val = m.get("aqi")
    if aqi_val is not None:
        lines.append(f"  • AQI: {aqi_val} ({_aqi_category(aqi_val)}) [{aqi_prov_str}]")
    else:
        lines.append("  • AQI: unavailable")

    lst_val = m.get("lst")
    if lst_val is not None:
        lines.append(f"  • LST: {lst_val:.2f} °C")
    else:
        lines.append(
            "  • LST: unavailable — no valid Landsat scene was acquired for this snapshot window."
        )

    ndvi_val = m.get("ndvi")
    lines.append(f"  • NDVI: {_fmt_float(ndvi_val)}" if ndvi_val is not None else "  • NDVI: unavailable")
    ndwi_val = m.get("ndwi")
    lines.append(f"  • NDWI: {_fmt_float(ndwi_val)}" if ndwi_val is not None else "  • NDWI: unavailable")
    mndwi_val = m.get("mndwi")
    lines.append(f"  • MNDWI water detection index: {_fmt_float(mndwi_val)}" if mndwi_val is not None else "  • MNDWI water detection index: unavailable")
    ndci_val = m.get("ndci")
    lines.append(f"  • NDCI algal/chlorophyll-related proxy: {_fmt_float(ndci_val)}" if ndci_val is not None else "  • NDCI algal/chlorophyll-related proxy: unavailable")
    turbidity_val = m.get("turbidity_proxy")
    lines.append(f"  • Turbidity/suspended-material relative signal: {_fmt_float(turbidity_val)}" if turbidity_val is not None else "  • Turbidity/suspended-material relative signal: unavailable")
    extent_val = m.get("water_extent_m2")
    lines.append(f"  • Water extent: {_fmt_float(extent_val, unit='m²')}" if extent_val is not None else "  • Water extent: unavailable")
    health_val = m.get("water_health_score")
    lines.append(f"  • Water Health score: {_fmt_float(health_val)}" if health_val is not None else "  • Water Health score: unavailable")

    return "\n".join(lines)


def _temporal_paragraph(metric: str, temporal_data: dict[str, Any]) -> str:
    label = _METRIC_LABELS.get(metric, metric.upper())
    if not temporal_data.get("available"):
        reason = temporal_data.get("reason", "not computed")
        return f"  • {label} temporal context: unavailable ({reason})."

    unavailable_reason = temporal_data.get("unavailable_reason")

    prev = temporal_data.get("previous_observation")
    if prev is None:
        return (
            f"  • {label} temporal context: unavailable — no prior compatible observation exists yet."
        )

    delta = temporal_data.get("delta")
    rate = temporal_data.get("rate_per_day")
    elapsed = prev.get("elapsed_days")
    elapsed_str = f"{elapsed:.1f} days" if elapsed is not None else "unknown interval"

    lines = [
        f"  • {label}:",
        f"    – Change since prior observation ({elapsed_str} ago): {_fmt_float(delta)} (Δ)",
        f"    – Rate of change: {_fmt_float(rate)} per day",
    ]

    baseline = temporal_data.get("baseline")
    if baseline:
        lines.append(
            f"    – Historical baseline mean: {_fmt_float(baseline.get('mean'))} "
            f"(n={baseline.get('count')}, σ={_fmt_float(baseline.get('standard_deviation'))})"
        )
        z = baseline.get("z_score")
        if z is not None:
            lines.append(f"    – Current deviation from historical baseline: {_sigma(z)}")
    else:
        if unavailable_reason == "insufficient_compatible_history_for_baseline":
            lines.append("    – Historical baseline: unavailable (fewer than 3 prior compatible observations).")
        else:
            lines.append("    – Historical baseline: unavailable.")

    trend = temporal_data.get("trend")
    if trend:
        slope = trend.get("slope_per_day")
        direction = trend.get("direction", "unavailable")
        n = trend.get("observations_used", 0)
        lines.append(
            f"    – Trend: {direction} ({_fmt_float(slope)} per day, {n} observations)."
        )
    else:
        lines.append("    – Historical trend: unavailable (insufficient compatible observations).")

    return "\n".join(lines)


def _persistence_paragraph(evidence: dict[str, Any]) -> str:
    persistence = evidence["anomaly_persistence"]
    if not persistence.get("available"):
        reason = persistence.get("unavailable_reason", "insufficient prior spatial snapshots")
        return f"Anomaly persistence: unavailable ({reason})."

    streak = persistence.get("prior_anomaly_streak")
    count = persistence.get("prior_anomaly_count")
    classification = persistence.get("classification", "unavailable")

    streak_str = f"{streak} consecutive" if streak is not None else "unknown"
    count_str = str(count) if count is not None else "unknown"
    return (
        f"Anomaly persistence: {classification} "
        f"(prior anomaly streak: {streak_str}, total prior anomalies: {count_str})."
    )


def _provenance_paragraph(evidence: dict[str, Any]) -> str:
    prov = evidence["provenance"]
    ndvi_ndwi = prov["satellite"].get("ndvi_ndwi") or {}
    lst_sat = prov["satellite"].get("lst") or {}

    ndvi_cfg = ndvi_ndwi.get("source_configuration") or {}
    ndvi_at = ndvi_ndwi.get("observed_at", "unknown")
    lst_at = lst_sat.get("observed_at", "unknown")

    dataset = ndvi_cfg.get("dataset", "COPERNICUS/S2_SR_HARMONIZED")
    window_days = ndvi_cfg.get("window_days", "?")
    cloud_mask = ndvi_cfg.get("cloud_mask", "QA60")

    lines = [
        "Source provenance:",
        f"  • NDVI/NDWI/Water Health: {dataset}, {window_days}-day composite, cloud-masked ({cloud_mask}), snapshot {str(ndvi_at)[:19]}.",
        f"  • LST: Landsat 8/9 Level-2, snapshot anchor {str(lst_at)[:19]}." if lst_at and lst_at != "unknown" else "  • LST: provenance not available for this snapshot.",
    ]
    return "\n".join(lines)


def _limitations_paragraph(evidence: dict[str, Any]) -> str:
    limitations = evidence.get("limitations") or []
    if not limitations:
        return "No explicit data limitations recorded for this evidence object."
    lines = ["Known data limitations:"]
    for item in limitations:
        lines.append(f"  • {item}")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

def generate_deterministic_explanation(evidence: dict[str, Any]) -> str:
    """Return a deterministic, evidence-grounded natural language explanation.

    The output is structured prose containing only facts that are present in
    the supplied evidence object.  No external lookups, no LLM, no inference.
    """
    paragraphs: list[str] = []

    # Classification
    paragraphs.append(_classification_sentence(evidence))

    # Measurements
    paragraphs.append(_measurements_paragraph(evidence))

    # Dominant deviations (root-cause attribution — NOT physical causation)
    if evidence["isolation_forest"]["is_anomaly"]:
        paragraphs.append(_dominant_deviations_paragraph(evidence))

    # Temporal context for each metric
    temporal_lines = ["Temporal / historical context:"]
    for metric in ("aqi", "ndvi", "ndwi", "mndwi", "water_extent_m2", "water_health_score", "lst"):
        temporal_lines.append(
            _temporal_paragraph(metric, evidence["temporal_context"].get(metric, {"available": False}))
        )
    paragraphs.append("\n".join(temporal_lines))

    # Anomaly persistence
    paragraphs.append(_persistence_paragraph(evidence))

    # Provenance
    paragraphs.append(_provenance_paragraph(evidence))

    # Limitations
    paragraphs.append(_limitations_paragraph(evidence))

    return "\n\n".join(paragraphs)
