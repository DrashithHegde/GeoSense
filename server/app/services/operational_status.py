"""Read-only operational visibility for GeoSense's existing data pipeline."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text


SPATIAL_MODEL_NAME = "isolation_forest_spatial_v1"
METRICS = {
    "aqi": "aqi",
    "lst": "lst",
    "ndvi": "ndvi_ndwi",
    "ndwi": "ndvi_ndwi",
}


def _one(db, query: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return dict(db.execute(text(query), params or {}).mappings().one())


def summarize_temporal_readiness(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Format prior-only eligibility counts returned by the read-only query."""
    return {
        row["metric"]: {
            "current_zone_metric_combinations": int(row["current_combinations"]),
            "at_least_1_prior": int(row["at_least_1_prior"]),
            "at_least_3_prior": int(row["at_least_3_prior"]),
            "trend_ready": int(row["trend_ready"]),
        }
        for row in rows
    }


def _metric_history(db, metric: str, metadata_key: str) -> dict[str, Any]:
    return _one(
        db,
        f"""
        SELECT count(*) AS non_null_observations,
               count(DISTINCT observed_at) AS distinct_timestamps,
               min(observed_at) AS earliest_observation,
               max(observed_at) AS latest_observation,
               count(DISTINCT zone_id) AS zones_represented,
               count(*) FILTER (WHERE source_metadata ? :metadata_key) AS provenance_bearing_observations
        FROM environment_data
        WHERE {metric} IS NOT NULL
        """,
        {"metadata_key": metadata_key},
    )


def get_operational_status(db) -> dict[str, Any]:
    """Build an API-safe status report using SELECT queries only."""
    raw = _one(
        db,
        """
        SELECT (SELECT count(*) FROM zones) AS total_zones,
               count(*) AS total_environment_data_rows,
               count(DISTINCT (zone_id, observed_at)) AS distinct_zone_timestamp_rows,
               count(*) - count(DISTINCT (zone_id, observed_at)) AS duplicate_zone_timestamp_rows,
               min(observed_at) AS earliest_raw_observation,
               max(observed_at) AS latest_raw_observation
        FROM environment_data
        """,
    )
    metrics = {metric: _metric_history(db, metric, metadata_key) for metric, metadata_key in METRICS.items()}
    aqi = _one(
        db,
        """
        WITH latest AS (
            SELECT max(observed_at) AS observed_at
            FROM environment_data
            WHERE aqi IS NOT NULL OR aqi_source_type IS NOT NULL
        )
        SELECT latest.observed_at AS latest_aqi_timestamp,
               count(*) FILTER (WHERE e.aqi_source_type = 'observed') AS observed_count,
               count(*) FILTER (WHERE e.aqi_source_type = 'estimated') AS estimated_count,
               count(*) FILTER (WHERE e.aqi IS NULL) AS uncovered_count
        FROM latest
        LEFT JOIN environment_data e ON e.observed_at = latest.observed_at
        GROUP BY latest.observed_at
        """,
    )
    temporal_rows = db.execute(
        text(
            """
            WITH observations AS (
                SELECT zone_id, 'aqi'::text AS metric, observed_at, aqi_source_type,
                       (source_metadata -> 'aqi') - 'window_start' - 'window_end' AS processing_context
                FROM environment_data WHERE aqi IS NOT NULL
                UNION ALL
                SELECT zone_id, 'lst', observed_at, NULL,
                       (source_metadata -> 'lst') - 'window_start' - 'window_end'
                FROM environment_data WHERE lst IS NOT NULL
                UNION ALL
                SELECT zone_id, 'ndvi', observed_at, NULL,
                       (source_metadata -> 'ndvi_ndwi') - 'window_start' - 'window_end'
                FROM environment_data WHERE ndvi IS NOT NULL
                UNION ALL
                SELECT zone_id, 'ndwi', observed_at, NULL,
                       (source_metadata -> 'ndvi_ndwi') - 'window_start' - 'window_end'
                FROM environment_data WHERE ndwi IS NOT NULL
            ), current_observations AS (
                SELECT DISTINCT ON (zone_id, metric) zone_id, metric, observed_at, aqi_source_type, processing_context
                FROM observations
                WHERE processing_context IS NOT NULL
                ORDER BY zone_id, metric, observed_at DESC
            ), prior_counts AS (
                SELECT current.metric, current.zone_id, count(prior.*)::int AS prior_count
                FROM current_observations current
                LEFT JOIN observations prior ON prior.zone_id = current.zone_id
                    AND prior.metric = current.metric
                    AND prior.observed_at < current.observed_at
                    AND prior.processing_context = current.processing_context
                    AND (current.metric <> 'aqi' OR prior.aqi_source_type IS NOT DISTINCT FROM current.aqi_source_type)
                GROUP BY current.metric, current.zone_id
            )
            SELECT metric, count(*) AS current_combinations,
                   count(*) FILTER (WHERE prior_count >= 1) AS at_least_1_prior,
                   count(*) FILTER (WHERE prior_count >= 3) AS at_least_3_prior,
                   count(*) FILTER (WHERE prior_count >= 3) AS trend_ready
            FROM prior_counts GROUP BY metric ORDER BY metric
            """
        )
    ).mappings().all()
    temporal = summarize_temporal_readiness([dict(row) for row in temporal_rows])
    for metric in METRICS:
        temporal.setdefault(metric, {"current_zone_metric_combinations": 0, "at_least_1_prior": 0, "at_least_3_prior": 0, "trend_ready": 0})

    persistence = _one(
        db,
        """
        WITH current_results AS (
            SELECT DISTINCT ON (zone_id) zone_id, observed_at
            FROM anomaly_results WHERE model_name = :model_name
            ORDER BY zone_id, observed_at DESC
        ), prior_counts AS (
            SELECT current.zone_id, count(prior.*)::int AS prior_snapshots
            FROM current_results current
            LEFT JOIN anomaly_results prior ON prior.zone_id = current.zone_id
                AND prior.model_name = :model_name AND prior.observed_at < current.observed_at
            GROUP BY current.zone_id
        )
        SELECT count(*) AS current_zone_results,
               count(*) FILTER (WHERE prior_snapshots >= 3) AS persistence_ready
        FROM prior_counts
        """,
        {"model_name": SPATIAL_MODEL_NAME},
    )
    latest_feature = _one(
        db,
        """
        WITH latest AS (SELECT max(observed_at) AS observed_at FROM engineered_features)
        SELECT latest.observed_at AS snapshot_at, count(f.*) AS feature_rows,
               count(*) FILTER (WHERE (f.feature_values ->> 'model_eligible')::boolean) AS model_eligible_rows
        FROM latest LEFT JOIN engineered_features f ON f.observed_at = latest.observed_at
        GROUP BY latest.observed_at
        """,
    )
    latest_model = _one(
        db,
        """
        WITH latest AS (SELECT max(observed_at) AS observed_at FROM anomaly_results WHERE model_name = :model_name)
        SELECT latest.observed_at AS snapshot_at, count(a.*) AS result_rows,
               count(*) FILTER (WHERE a.is_anomaly) AS anomaly_rows
        FROM latest LEFT JOIN anomaly_results a ON a.observed_at = latest.observed_at AND a.model_name = :model_name
        GROUP BY latest.observed_at
        """,
        {"model_name": SPATIAL_MODEL_NAME},
    )
    temporal_any = any(item["at_least_1_prior"] > 0 for item in temporal.values())
    return {
        "read_only": True,
        "raw_data": raw,
        "metric_history": metrics,
        "aqi_latest_snapshot": aqi,
        "temporal_readiness": {
            "per_metric": temporal,
            "spatial_anomaly_persistence": {
                "current_zone_results": int(persistence["current_zone_results"]),
                "at_least_3_prior_snapshots": int(persistence["persistence_ready"]),
            },
            "minimum_history_policy": {"delta_rate_prior_observations": 1, "baseline_trend_prior_observations": 3, "persistence_prior_snapshots": 3},
        },
        "pipeline_readiness": {
            "spatial_feature_pipeline": {"ready": int(latest_feature["feature_rows"]) > 0, **latest_feature},
            "spatial_isolation_forest": {"ready": int(latest_model["result_rows"]) >= 20, "model_name": SPATIAL_MODEL_NAME, **latest_model},
            "temporal_feature_calculations": {"ready": temporal_any, "reason": None if temporal_any else "insufficient compatible provenance-bearing history"},
            "future_temporal_modeling": {"ready": False, "reason": "insufficient real historical depth"},
            "xgboost": {"target_defined": False, "training_ready": False, "reason": "no legitimate supervised target"},
        },
        "scheduler": {
            "status": "unavailable",
            "reason": "Scheduler run state is in-process only and is not persisted in the database.",
            "configured_cadence": {"aqi_idw": "every 3 hours", "sentinel_2_ndvi_ndwi": "every 7 days", "landsat_lst": "every 14 days", "feature_anomaly": "after same-day successful AQI and satellite sources"},
        },
    }
