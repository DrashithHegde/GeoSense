"""Leakage-safe temporal context built from real, source-compatible observations.

This module never writes raw observations.  It compares each metric using that
metric's actual source timestamp and only uses records strictly before it.
"""
from __future__ import annotations

from datetime import datetime
from statistics import mean, median, stdev
from typing import Any

from sqlalchemy import select

from app.models import AnomalyResult, EnvironmentData


CORE_METRICS = ("aqi", "lst", "ndvi", "ndwi", "mndwi", "water_extent_m2", "water_health_score")
METRIC_METADATA_KEYS = {
    "aqi": "aqi",
    "lst": "lst",
    "ndvi": "ndvi_ndwi",
    "ndwi": "ndvi_ndwi",
    "mndwi": "water_health",
    "water_extent_m2": "water_health",
    "water_health_score": "water_health",
}
BASELINE_HISTORY_LIMIT = 12
MIN_BASELINE_OBSERVATIONS = 3
MIN_TREND_PRIOR_OBSERVATIONS = 3
PERSISTENCE_WINDOW = 5
MIN_PERSISTENCE_PRIOR_SNAPSHOTS = 3
WINDOW_INSTANCE_KEYS = frozenset({"window_start", "window_end"})


def _as_float(value: Any) -> float | None:
    return float(value) if value is not None else None


def temporal_processing_configuration(source_context: dict[str, Any]) -> dict[str, Any]:
    """Return stable processing settings, excluding a composite's date instance.

    Fixed-window Sentinel-2 and Landsat composites legitimately have different
    start/end dates on each scheduled observation. Those dates remain in the
    stored provenance, but must not make otherwise identical fixed-window
    processing incomparable through time.
    """
    return {key: value for key, value in source_context.items() if key not in WINDOW_INSTANCE_KEYS}


def source_contexts_are_temporally_compatible(
    current_context: dict[str, Any], prior_context: dict[str, Any]
) -> bool:
    return temporal_processing_configuration(current_context) == temporal_processing_configuration(prior_context)


def _trend(points: list[dict[str, Any]]) -> tuple[float | None, str, int]:
    """Ordinary least-squares slope using elapsed days, not row position."""
    if len(points) < MIN_TREND_PRIOR_OBSERVATIONS + 1:
        return None, "unavailable", len(points)
    first_time = points[0]["observed_at"]
    x_values = [(point["observed_at"] - first_time).total_seconds() / 86400.0 for point in points]
    y_values = [point["value"] for point in points]
    x_mean = mean(x_values)
    y_mean = mean(y_values)
    denominator = sum((x - x_mean) ** 2 for x in x_values)
    if denominator == 0:
        return None, "unavailable", len(points)
    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values)) / denominator
    direction = "increasing" if slope > 0 else "decreasing" if slope < 0 else "stable"
    return float(slope), direction, len(points)


def calculate_metric_context(
    *,
    metric: str,
    current: dict[str, Any],
    prior_observations: list[dict[str, Any]],
    metadata_context: dict[str, Any],
    aqi_source_type: str | None,
) -> dict[str, Any]:
    """Calculate prior-only temporal features for one source-compatible metric."""
    current_value = float(current["value"])
    prior_window = prior_observations[-BASELINE_HISTORY_LIMIT:]
    prior_count = len(prior_window)
    output: dict[str, Any] = {
        "metric": metric,
        "current": {
            "value": current_value,
            "observed_at": current["observed_at"].isoformat(),
            "environment_data_id": current["environment_data_id"],
        },
        "comparability": {
            "metadata_key": METRIC_METADATA_KEYS[metric],
            "source_configuration": metadata_context,
            "temporal_processing_configuration": temporal_processing_configuration(metadata_context),
            "window_instance_fields_excluded_from_comparison": sorted(WINDOW_INSTANCE_KEYS),
            "aqi_source_type": aqi_source_type if metric == "aqi" else None,
            "prior_compatible_observation_count": prior_count,
            "baseline_window": f"most recent {BASELINE_HISTORY_LIMIT} prior compatible observations",
        },
        "prior_observations_used": [
            {
                "value": observation["value"],
                "observed_at": observation["observed_at"].isoformat(),
                "environment_data_id": observation["environment_data_id"],
            }
            for observation in prior_window
        ],
        "previous_observation": None,
        "delta": None,
        "rate_per_day": None,
        "prior_baseline": {
            "count": prior_count,
            "mean": None,
            "median": None,
            "standard_deviation": None,
        },
        "historical_deviation_z_score": None,
        "trend": {
            "slope_per_day": None,
            "direction": "unavailable",
            "observations_used": 0,
        },
        "availability": {
            "previous_observation": prior_count >= 1,
            "baseline": prior_count >= MIN_BASELINE_OBSERVATIONS,
            "trend": prior_count >= MIN_TREND_PRIOR_OBSERVATIONS,
        },
    }
    if not prior_window:
        output["unavailable_reason"] = "insufficient_compatible_history"
        return output

    previous = prior_window[-1]
    elapsed_days = (current["observed_at"] - previous["observed_at"]).total_seconds() / 86400.0
    delta = current_value - previous["value"]
    output["previous_observation"] = {
        "value": previous["value"],
        "observed_at": previous["observed_at"].isoformat(),
        "environment_data_id": previous["environment_data_id"],
        "elapsed_days": elapsed_days,
    }
    output["delta"] = float(delta)
    output["rate_per_day"] = float(delta / elapsed_days) if elapsed_days > 0 else None

    if prior_count < MIN_BASELINE_OBSERVATIONS:
        output["unavailable_reason"] = "insufficient_compatible_history_for_baseline"
        return output

    values = [observation["value"] for observation in prior_window]
    baseline_mean = float(mean(values))
    baseline_std = float(stdev(values))
    output["prior_baseline"] = {
        "count": prior_count,
        "mean": baseline_mean,
        "median": float(median(values)),
        "standard_deviation": baseline_std,
    }
    if baseline_std > 0:
        output["historical_deviation_z_score"] = float((current_value - baseline_mean) / baseline_std)
    else:
        output["unavailable_reason"] = "zero_variance_prior_baseline"

    slope, direction, observations_used = _trend(prior_window + [current])
    output["trend"] = {
        "slope_per_day": slope,
        "direction": direction,
        "observations_used": observations_used,
    }
    return output


def _metric_context_from_raw(db, *, zone_id: int, metric: str, current: dict[str, Any]) -> dict[str, Any]:
    metadata_key = METRIC_METADATA_KEYS[metric]
    current_metadata = current.get("source_metadata") or {}
    source_configuration = current_metadata.get(metadata_key)
    aqi_source_type = current.get("aqi_source_type") if metric == "aqi" else None
    if source_configuration is None:
        return {
            "metric": metric,
            "current": {
                "value": _as_float(current["value"]),
                "observed_at": current["observed_at"].isoformat(),
                "environment_data_id": current["environment_data_id"],
            },
            "availability": {"previous_observation": False, "baseline": False, "trend": False},
            "unavailable_reason": "current_source_metadata_missing",
            "comparability": {
                "metadata_key": metadata_key,
                "source_configuration": None,
                "aqi_source_type": aqi_source_type,
                "prior_compatible_observation_count": 0,
            },
        }

    metric_column = getattr(EnvironmentData, metric)
    rows = db.execute(
        select(
            EnvironmentData.id,
            EnvironmentData.observed_at,
            metric_column.label("value"),
            EnvironmentData.source_metadata,
            EnvironmentData.aqi_source_type,
        )
        .where(
            EnvironmentData.zone_id == zone_id,
            EnvironmentData.observed_at < current["observed_at"],
            metric_column.is_not(None),
        )
        .order_by(EnvironmentData.observed_at.asc(), EnvironmentData.id.asc())
    ).mappings()
    prior_observations: list[dict[str, Any]] = []
    for row in rows:
        metadata = row["source_metadata"] or {}
        prior_context = metadata.get(metadata_key)
        if not isinstance(prior_context, dict) or not source_contexts_are_temporally_compatible(
            source_configuration, prior_context
        ):
            continue
        if metric == "aqi" and row["aqi_source_type"] != aqi_source_type:
            continue
        prior_observations.append(
            {
                "value": float(row["value"]),
                "observed_at": row["observed_at"],
                "environment_data_id": int(row["id"]),
            }
        )
    return calculate_metric_context(
        metric=metric,
        current=current,
        prior_observations=prior_observations,
        metadata_context=source_configuration,
        aqi_source_type=aqi_source_type,
    )


def prior_anomaly_persistence(db, *, zone_id: int, snapshot_at: datetime, model_name: str) -> dict[str, Any]:
    """Read only earlier spatial classifications; current/future results are excluded."""
    rows = db.execute(
        select(AnomalyResult.observed_at, AnomalyResult.is_anomaly)
        .where(
            AnomalyResult.zone_id == zone_id,
            AnomalyResult.model_name == model_name,
            AnomalyResult.observed_at < snapshot_at,
        )
        .order_by(AnomalyResult.observed_at.desc())
        .limit(PERSISTENCE_WINDOW)
    ).mappings().all()
    chronological = list(reversed(rows))
    prior_streak = 0
    for row in rows:
        if not row["is_anomaly"]:
            break
        prior_streak += 1
    available = len(chronological) >= MIN_PERSISTENCE_PRIOR_SNAPSHOTS
    return {
        "window_size": PERSISTENCE_WINDOW,
        "minimum_prior_snapshots": MIN_PERSISTENCE_PRIOR_SNAPSHOTS,
        "prior_valid_snapshot_count": len(chronological),
        "prior_anomaly_count": sum(1 for row in chronological if row["is_anomaly"]) if available else None,
        "prior_anomaly_streak": prior_streak if available else None,
        "availability": available,
        "unavailable_reason": None if available else "insufficient_prior_spatial_anomaly_history",
        "prior_snapshots": [
            {"observed_at": row["observed_at"].isoformat(), "is_anomaly": bool(row["is_anomaly"])}
            for row in chronological
        ],
    }


def finalize_anomaly_persistence(prior_context: dict[str, Any], current_is_anomaly: bool | None) -> dict[str, Any]:
    """Add current classification after spatial Isolation Forest has run."""
    result = dict(prior_context)
    result["current_spatial_anomaly_available"] = current_is_anomaly is not None
    result["current_is_anomaly"] = current_is_anomaly
    result["current_anomaly_streak"] = None
    result["classification"] = "unavailable"
    if current_is_anomaly is None:
        result["unavailable_reason"] = "current_zone_not_eligible_for_spatial_model"
        return result
    if not prior_context["availability"]:
        return result
    current_streak = prior_context["prior_anomaly_streak"] + 1 if current_is_anomaly else 0
    result["current_anomaly_streak"] = current_streak
    if not current_is_anomaly:
        result["classification"] = "not_currently_anomalous"
    elif current_streak >= 3:
        result["classification"] = "persistent"
    else:
        result["classification"] = "isolated_or_not_yet_persistent"
    return result


def build_temporal_contexts(db, snapshot_rows: list[dict[str, Any]], snapshot_at: datetime, model_name: str) -> dict[int, dict[str, Any]]:
    """Build temporal evidence for all source values in an analytical snapshot."""
    contexts: dict[int, dict[str, Any]] = {}
    for row in snapshot_rows:
        metrics = {
            metric: _metric_context_from_raw(db, zone_id=row["zone_id"], metric=metric, current=row["sources"][metric])
            for metric in CORE_METRICS
            if metric in row["sources"]
        }
        contexts[row["zone_id"]] = {
            "schema_version": "1.0",
            "calculation_policy": {
                "raw_history_only": True,
                "current_excluded_from_baselines": True,
                "future_observations_excluded": True,
                "forward_fill": False,
                "baseline_minimum_prior_observations": MIN_BASELINE_OBSERVATIONS,
                "trend_minimum_prior_observations": MIN_TREND_PRIOR_OBSERVATIONS,
            },
            "metrics": metrics,
            "spatial_anomaly_persistence": prior_anomaly_persistence(
                db,
                zone_id=row["zone_id"],
                snapshot_at=snapshot_at,
                model_name=model_name,
            ),
        }
    return contexts
