"""Evidence retrieval and validation for the GeoSense explanation layer.

This module is the ONLY layer allowed to touch the database for explanation
purposes.  It assembles a validated, structured evidence object from persisted
rows in environment_data, engineered_features, and anomaly_results.

Design rules:
- Never invent, forward-fill, interpolate, or infer a missing value.
- Every NULL in the database becomes an explicit None / "unavailable" marker.
- The evidence object is what the deterministic explanation engine and any
  future LLM/RAG layer receive.  No other code in the explanation pipeline
  touches the database directly.
- Nothing here modifies the database.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text

from app.models import AnomalyResult, EngineeredFeature, EnvironmentData, Zone

# ──────────────────────────────────────────────────────────────
# Public sentinel values
# ──────────────────────────────────────────────────────────────
UNAVAILABLE = "unavailable"


# ──────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────

def _safe_float(value: Any) -> float | None:
    """Return float or None; never raises."""
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _extract_aqi_provenance(evidence_json: dict[str, Any]) -> dict[str, Any]:
    prov = evidence_json.get("aqi_provenance") or {}
    return {
        "source_type": prov.get("source_type"),           # "observed" | "estimated" | None
        "nearest_station_distance_m": _safe_float(prov.get("nearest_station_distance_m")),
    }


def _extract_satellite_provenance(evidence_json: dict[str, Any]) -> dict[str, Any]:
    """Pull Sentinel-2 / Landsat composite window details from stored evidence."""
    source_records = evidence_json.get("source_records") or {}
    ndvi_source = source_records.get("ndvi") or {}
    lst_source = source_records.get("lst") or {}

    temporal_ctx = evidence_json.get("temporal_context") or {}
    metrics = temporal_ctx.get("metrics") or {}
    ndvi_meta = (metrics.get("ndvi") or {}).get("comparability") or {}
    lst_meta = (metrics.get("lst") or {}).get("comparability") or {}

    return {
        "ndvi_ndwi": {
            "observed_at": ndvi_source.get("observed_at"),
            "source_configuration": ndvi_meta.get("source_configuration"),
        },
        "water_health": {
            "observed_at": ndvi_source.get("observed_at"),
            "source_configuration": ndvi_meta.get("source_configuration"),
        },
        "lst": {
            "observed_at": lst_source.get("observed_at"),
            "source_configuration": lst_meta.get("source_configuration"),
        },
    }


def _extract_temporal_context_for_metric(
    metric: str, temporal_ctx: dict[str, Any]
) -> dict[str, Any]:
    """Extract only what the temporal engine explicitly computed for one metric."""
    metrics = temporal_ctx.get("metrics") or {}
    metric_data = metrics.get(metric)
    if metric_data is None:
        return {"available": False, "reason": "metric_not_in_temporal_context"}

    availability = metric_data.get("availability") or {}
    has_previous = bool(availability.get("previous_observation"))
    has_baseline = bool(availability.get("baseline"))
    has_trend = bool(availability.get("trend"))
    unavailable_reason = metric_data.get("unavailable_reason")

    result: dict[str, Any] = {
        "available": True,
        "unavailable_reason": unavailable_reason,
        "previous_observation": None,
        "delta": None,
        "rate_per_day": None,
        "baseline": None,
        "trend": None,
    }

    if has_previous:
        prev = metric_data.get("previous_observation") or {}
        result["previous_observation"] = {
            "value": _safe_float(prev.get("value")),
            "observed_at": prev.get("observed_at"),
            "elapsed_days": _safe_float(prev.get("elapsed_days")),
        }
        result["delta"] = _safe_float(metric_data.get("delta"))
        result["rate_per_day"] = _safe_float(metric_data.get("rate_per_day"))

    if has_baseline:
        pb = metric_data.get("prior_baseline") or {}
        result["baseline"] = {
            "count": _safe_int(pb.get("count")),
            "mean": _safe_float(pb.get("mean")),
            "median": _safe_float(pb.get("median")),
            "standard_deviation": _safe_float(pb.get("standard_deviation")),
            "z_score": _safe_float(metric_data.get("historical_deviation_z_score")),
        }

    if has_trend:
        tr = metric_data.get("trend") or {}
        result["trend"] = {
            "slope_per_day": _safe_float(tr.get("slope_per_day")),
            "direction": tr.get("direction", UNAVAILABLE),
            "observations_used": _safe_int(tr.get("observations_used")),
        }

    return result


def _extract_anomaly_persistence(temporal_ctx: dict[str, Any]) -> dict[str, Any]:
    persistence = temporal_ctx.get("spatial_anomaly_persistence") or {}
    return {
        "available": bool(persistence.get("availability")),
        "prior_anomaly_count": _safe_int(persistence.get("prior_anomaly_count")),
        "prior_anomaly_streak": _safe_int(persistence.get("prior_anomaly_streak")),
        "classification": persistence.get("classification", UNAVAILABLE),
        "unavailable_reason": persistence.get("unavailable_reason"),
    }


# ──────────────────────────────────────────────────────────────
# Public evidence assembly
# ──────────────────────────────────────────────────────────────

class ZoneNotFoundError(ValueError):
    pass


class NoAnomalyResultError(ValueError):
    pass


def build_zone_evidence(db, zone_id: int) -> dict[str, Any]:
    """Assemble a validated evidence object for a zone from its latest anomaly result.

    Returns a structured dict.  Raises ZoneNotFoundError if the zone does not
    exist, and NoAnomalyResultError if no Isolation Forest result has ever been
    persisted for this zone.  Both cases are handled transparently at the API
    layer.
    """
    # ── 1. Verify zone exists ────────────────────────────────
    zone_row = db.execute(
        select(Zone.id, Zone.name, Zone.ward).where(Zone.id == zone_id)
    ).mappings().first()
    if zone_row is None:
        raise ZoneNotFoundError(f"Zone {zone_id} not found")
    zone_info = dict(zone_row)

    # ── 2. Latest anomaly result for this zone ───────────────
    anomaly_row = db.execute(
        select(
            AnomalyResult.id,
            AnomalyResult.observed_at,
            AnomalyResult.detected_at,
            AnomalyResult.anomaly_score,
            AnomalyResult.is_anomaly,
            AnomalyResult.anomaly_type,
            AnomalyResult.root_cause,
            AnomalyResult.evidence,
        )
        .where(
            AnomalyResult.zone_id == zone_id,
            AnomalyResult.model_name == "isolation_forest_spatial_v1",
        )
        .order_by(AnomalyResult.observed_at.desc())
        .limit(1)
    ).mappings().first()

    if anomaly_row is None:
        raise NoAnomalyResultError(f"No Isolation Forest result found for zone {zone_id}")

    anomaly = dict(anomaly_row)
    evidence_json: dict[str, Any] = anomaly.get("evidence") or {}
    temporal_ctx: dict[str, Any] = evidence_json.get("temporal_context") or {}

    # ── 3. Raw measurements (from persisted evidence JSON) ───
    raw_values: dict[str, Any] = evidence_json.get("raw_values") or {}
    measurements = {
        "aqi":  _safe_int(raw_values.get("aqi")),
        "lst":  _safe_float(raw_values.get("lst")),
        "ndvi": _safe_float(raw_values.get("ndvi")),
        "ndwi": _safe_float(raw_values.get("ndwi")),
        "mndwi": _safe_float(raw_values.get("mndwi")),
        "ndci": _safe_float(raw_values.get("ndci")),
        "turbidity_proxy": _safe_float(raw_values.get("turbidity_proxy")),
        "water_extent_m2": _safe_float(raw_values.get("water_extent_m2")),
        "water_health_score": _safe_float(raw_values.get("water_health_score")),
        "water_health_status": raw_values.get("water_health_status"),
        "pm25": _safe_float(raw_values.get("pm25")),
        "pm10": _safe_float(raw_values.get("pm10")),
        "no2":  _safe_float(raw_values.get("no2")),
    }

    # ── 4. Isolation Forest outputs ──────────────────────────
    model_evidence = evidence_json.get("model") or {}
    feature_z_scores: dict[str, float] = {
        k: float(v)
        for k, v in (evidence_json.get("feature_z_scores") or {}).items()
    }
    dominant_deviations: list[dict[str, Any]] = evidence_json.get("dominant_deviations") or []

    isolation_forest = {
        "model_name": model_evidence.get("name", "isolation_forest_spatial_v1"),
        "snapshot_date": evidence_json.get("snapshot_date"),
        "is_anomaly": bool(anomaly["is_anomaly"]),
        "anomaly_score": _safe_float(anomaly["anomaly_score"]),
        "anomaly_type": anomaly.get("anomaly_type"),
        "root_cause_string": anomaly.get("root_cause"),
        "feature_z_scores": feature_z_scores,
        "dominant_deviations": dominant_deviations,
        "features_used": model_evidence.get("feature_order") or [],
        "features_excluded_constant": model_evidence.get("excluded_constant_features") or [],
    }

    # ── 5. Temporal context per metric ───────────────────────
    temporal = {
        metric: _extract_temporal_context_for_metric(metric, temporal_ctx)
        for metric in ("aqi", "lst", "ndvi", "ndwi", "mndwi", "water_extent_m2", "water_health_score")
    }

    # ── 6. Anomaly persistence ───────────────────────────────
    anomaly_persistence = _extract_anomaly_persistence(temporal_ctx)

    # ── 7. Provenance ────────────────────────────────────────
    aqi_prov = _extract_aqi_provenance(evidence_json)
    satellite_prov = _extract_satellite_provenance(evidence_json)

    # ── 8. Limitations — what we explicitly do NOT know ──────
    limitations: list[str] = []
    if measurements["lst"] is None:
        limitations.append("LST is unavailable for this analytical snapshot (no valid Landsat scene).")
    if measurements["aqi"] is None:
        limitations.append("AQI is unavailable for this analytical snapshot.")
    if aqi_prov["source_type"] == "estimated":
        dist = aqi_prov["nearest_station_distance_m"]
        dist_str = f"{dist:.0f} m" if dist is not None else "unknown distance"
        limitations.append(f"AQI is IDW-estimated (nearest station: {dist_str}), not a direct station observation.")
    for metric in ("aqi", "lst", "ndvi", "ndwi", "mndwi", "water_extent_m2", "water_health_score"):
        if not temporal[metric].get("previous_observation"):
            limitations.append(
                f"Temporal delta/rate for {metric.upper()} is unavailable (insufficient prior compatible observations)."
            )
        if not temporal[metric].get("baseline"):
            limitations.append(
                f"Historical baseline for {metric.upper()} is unavailable (fewer than 3 prior compatible observations)."
            )
    if not anomaly_persistence["available"]:
        limitations.append("Anomaly persistence classification is unavailable (fewer than 3 prior spatial snapshots).")
    if measurements["mndwi"] is not None and measurements["water_health_score"] is None:
        limitations.append("Water Health score is unavailable because condition evidence was insufficient.")

    return {
        "schema_version": "1.0",
        "evidence_generated_at": datetime.now(timezone.utc).isoformat(),
        "zone": zone_info,
        "analysis_timestamp": _iso(anomaly["observed_at"]),
        "detected_at": _iso(anomaly["detected_at"]),
        "measurements": measurements,
        "isolation_forest": isolation_forest,
        "temporal_context": temporal,
        "anomaly_persistence": anomaly_persistence,
        "provenance": {
            "aqi": aqi_prov,
            "satellite": satellite_prov,
        },
        "limitations": limitations,
    }
