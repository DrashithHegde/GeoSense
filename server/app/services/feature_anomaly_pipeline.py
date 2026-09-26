"""Feature engineering and spatial Isolation Forest for real GeoSense observations.

The pipeline creates a UTC-date snapshot by selecting each zone's latest non-null
measurement for every variable within that date.  It never fills a missing raw
measurement: rows without all four core variables are retained as feature rows
but excluded from the Isolation Forest cohort.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
import json
from typing import Any

import numpy as np
from sklearn import __version__ as sklearn_version
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sqlalchemy import select, text

from app.database import get_db
from app.models import EnvironmentData, Zone
from app.services.temporal_features import build_temporal_contexts, finalize_anomaly_persistence


MODEL_NAME = "isolation_forest_spatial_v1"
MODEL_FEATURES = ("aqi", "lst", "ndvi", "ndwi")
MODEL_RANDOM_STATE = 42
MODEL_CONTAMINATION = 0.10
MODEL_ESTIMATORS = 200
MIN_MODEL_ROWS = 20


def _utc_day_bounds(snapshot_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(snapshot_date, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def _as_json_value(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _relative_score(value: float | None, values: list[float], inverse: bool = False) -> float | None:
    """Return a same-snapshot 0..1 directional severity, without making a composite risk."""
    if value is None or not values:
        return None
    low, high = min(values), max(values)
    if high == low:
        return 0.5
    score = (value - low) / (high - low)
    return float(1.0 - score if inverse else score)


def _load_snapshot(db, snapshot_date: date, is_legacy_zone: bool = False) -> tuple[list[dict[str, Any]], dict[int, dict[str, dict[str, Any]]]]:
    """Load current-day, per-metric source values without cross-day imputation."""
    start, end = _utc_day_bounds(snapshot_date)
    if is_legacy_zone:
        locations = {
            row.id: {"loc_id": row.id, "location_name": row.name}
            for row in db.execute(select(Zone.id, Zone.name).order_by(Zone.id))
        }
    else:
        from app.models import SpatialCell
        locations = {
            row.id: {"loc_id": row.id, "location_name": row.municipality_name}
            for row in db.execute(select(SpatialCell.id, SpatialCell.municipality_name).order_by(SpatialCell.id))
        }
    selected: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
    fields = (*MODEL_FEATURES, "mndwi", "water_extent_m2", "water_health_score", "pm25", "pm10", "no2")
    rows = db.execute(
        select(
            EnvironmentData.id,
            EnvironmentData.zone_id if is_legacy_zone else EnvironmentData.cell_id,
            EnvironmentData.observed_at,
            EnvironmentData.aqi,
            EnvironmentData.lst,
            EnvironmentData.ndvi,
            EnvironmentData.ndwi,
            EnvironmentData.mndwi,
            EnvironmentData.water_extent_m2,
            EnvironmentData.water_health_score,
            EnvironmentData.pm25,
            EnvironmentData.pm10,
            EnvironmentData.no2,
            EnvironmentData.aqi_source_type,
            EnvironmentData.aqi_nearest_station_distance_m,
            EnvironmentData.source_metadata,
        )
        .where(EnvironmentData.observed_at >= start, EnvironmentData.observed_at < end)
        .where((EnvironmentData.zone_id.isnot(None)) if is_legacy_zone else (EnvironmentData.cell_id.isnot(None)))
        .order_by(EnvironmentData.observed_at.asc(), EnvironmentData.id.asc())
    ).mappings()
    for row in rows:
        for field in fields:
            value = row[field]
            if value is not None:
                selected[row[1]][field] = {
                    "value": float(value),
                    "environment_data_id": int(row["id"]),
                    "observed_at": row["observed_at"],
                    "aqi_source_type": row["aqi_source_type"] if field == "aqi" else None,
                    "aqi_nearest_station_distance_m": row["aqi_nearest_station_distance_m"] if field == "aqi" else None,
                    "source_metadata": row["source_metadata"] or {},
                }

    snapshot_rows: list[dict[str, Any]] = []
    for loc_id, loc in locations.items():
        metric_sources = selected.get(loc_id, {})
        values = {field: metric_sources.get(field, {}).get("value") for field in fields}
        # Prefer the satellite record as the relational anchor: it shares the canonical
        # midnight snapshot timestamp and normally carries NDVI, NDWI, and LST together.
        # AQI's own source record remains explicitly available in source_records.
        source_ids = [
            metric_sources[field]["environment_data_id"]
            for field in ("ndvi", "ndwi", "lst", "mndwi", "water_extent_m2", "water_health_score", "aqi", "pm25", "pm10", "no2")
            if field in metric_sources
        ]
        snapshot_rows.append(
            {
                **loc,
                "values": values,
                "sources": metric_sources,
                "environment_data_id": next(iter(source_ids), None),
            }
        )
    return snapshot_rows, selected


def _modelable_count(snapshot_rows: list[dict[str, Any]]) -> int:
    return sum(all(row["values"][field] is not None for field in MODEL_FEATURES) for row in snapshot_rows)


def _missing_core_metrics(row: dict[str, Any]) -> list[str]:
    return [field for field in MODEL_FEATURES if row["values"][field] is None]


def _validated_model_matrix(eligible_rows: list[dict[str, Any]]) -> np.ndarray:
    """Build the production matrix only after explicit size and numeric checks."""
    if not eligible_rows:
        raise ValueError("No complete AQI, LST, NDVI, and NDWI rows are available; no model results were written")
    if len(eligible_rows) < MIN_MODEL_ROWS:
        raise ValueError(
            f"Only {len(eligible_rows)} complete rows are available; at least {MIN_MODEL_ROWS} are required for Isolation Forest"
        )
    matrix = np.asarray([[row["values"][field] for field in MODEL_FEATURES] for row in eligible_rows], dtype=float)
    invalid = ~np.isfinite(matrix)
    if invalid.any():
        affected_locs = sorted({eligible_rows[index]["loc_id"] for index in np.where(invalid)[0]})
        raise ValueError(
            "Non-finite core feature values detected for zone IDs "
            f"{affected_locs}; Isolation Forest was not run and no derived rows were written"
        )
    return matrix


def _select_varying_model_features(matrix: np.ndarray) -> tuple[tuple[str, ...], np.ndarray, tuple[str, ...]]:
    """Exclude only snapshot-constant predictors, which carry no spatial signal."""
    active_positions = [position for position in range(matrix.shape[1]) if np.ptp(matrix[:, position]) > 0]
    active_features = tuple(MODEL_FEATURES[position] for position in active_positions)
    excluded_features = tuple(feature for feature in MODEL_FEATURES if feature not in active_features)
    if not active_features:
        raise ValueError("All complete model predictors are constant in this snapshot; Isolation Forest was not run")
    return active_features, matrix[:, active_positions], excluded_features


def _find_snapshot_date(db, is_legacy_zone: bool = False) -> date:
    timestamps = db.execute(select(EnvironmentData.observed_at).order_by(EnvironmentData.observed_at.desc())).scalars()
    candidate_dates = sorted({timestamp.astimezone(timezone.utc).date() for timestamp in timestamps}, reverse=True)
    for candidate in candidate_dates:
        rows, _ = _load_snapshot(db, candidate, is_legacy_zone=is_legacy_zone)
        if _modelable_count(rows) >= MIN_MODEL_ROWS:
            return candidate
    raise ValueError("No UTC date has enough complete AQI, NDVI, NDWI, and LST measurements for Isolation Forest")


def _dominant_deviations(
    zscores: dict[str, float], raw_values: dict[str, float | None], feature_names: tuple[str, ...]
) -> list[dict[str, Any]]:
    labels = {"aqi": "AQI", "lst": "LST", "ndvi": "NDVI", "ndwi": "NDWI"}
    ordered = sorted(feature_names, key=lambda field: abs(zscores[field]), reverse=True)
    return [
        {
            "variable": field,
            "label": labels[field],
            "direction": "above" if zscores[field] >= 0 else "below",
            "z_score": round(float(zscores[field]), 4),
            "value": raw_values[field],
        }
        for field in ordered
    ]


def run_feature_anomaly_pipeline(snapshot_date: date | None = None, is_legacy_zone: bool = False) -> dict[str, Any]:
    """Upsert feature rows and one Isolation Forest classification per eligible zone."""
    with get_db() as db:
        selected_date = snapshot_date or _find_snapshot_date(db, is_legacy_zone=is_legacy_zone)
        snapshot_at, _ = _utc_day_bounds(selected_date)
        snapshot_rows, _ = _load_snapshot(db, selected_date, is_legacy_zone=is_legacy_zone)
        for row in snapshot_rows:
            row["missing_core_metrics"] = _missing_core_metrics(row)
        eligible_rows = [row for row in snapshot_rows if not row["missing_core_metrics"]]
        raw_matrix = _validated_model_matrix(eligible_rows)
        active_model_features, model_matrix, excluded_constant_features = _select_varying_model_features(raw_matrix)
        temporal_contexts = build_temporal_contexts(db, snapshot_rows, snapshot_at, MODEL_NAME)

        available_values = {
            field: [row["values"][field] for row in snapshot_rows if row["values"][field] is not None]
            for field in MODEL_FEATURES
        }
        scaler = StandardScaler()
        scaled_matrix = scaler.fit_transform(model_matrix)
        model = IsolationForest(
            n_estimators=MODEL_ESTIMATORS,
            contamination=MODEL_CONTAMINATION,
            random_state=MODEL_RANDOM_STATE,
        )
        predictions = model.fit_predict(scaled_matrix)
        raw_anomaly_scores = -model.score_samples(scaled_matrix)  # Higher means more isolated/anomalous.

        model_index = {row["loc_id"]: index for index, row in enumerate(eligible_rows)}
        engineered_feature_ids: dict[int, int] = {}
        feature_value_records: dict[int, dict[str, Any]] = {}
        for row in snapshot_rows:
            values = row["values"]
            aqi_source = row["sources"].get("aqi", {})
            relative_stress = {
                "pollution": _relative_score(values["aqi"], available_values["aqi"]),
                "heat": _relative_score(values["lst"], available_values["lst"]),
                "vegetation": _relative_score(values["ndvi"], available_values["ndvi"], inverse=True),
                "moisture": _relative_score(values["ndwi"], available_values["ndwi"], inverse=True),
            }
            source_evidence = {
                field: {
                    "environment_data_id": source["environment_data_id"],
                    "observed_at": source["observed_at"].isoformat(),
                }
                for field, source in row["sources"].items()
            }
            feature_values: dict[str, Any] = {
                "schema_version": "1.0",
                "snapshot_date": selected_date.isoformat(),
                "selection_method": "latest non-null value per metric within the UTC snapshot date",
                "raw_values": values,
                "relative_stress": relative_stress,
                "source_records": source_evidence,
                "aqi_provenance": {
                    "source_type": aqi_source.get("aqi_source_type"),
                    "nearest_station_distance_m": _as_json_value(aqi_source.get("aqi_nearest_station_distance_m")),
                },
                "temporal_context": temporal_contexts[row["loc_id"]],
                "model_eligible": row["loc_id"] in model_index,
                "model_input_features": list(active_model_features),
                "model_excluded_constant_features": list(excluded_constant_features),
                "model_ineligible_reason": (
                    None
                    if row["loc_id"] in model_index
                    else {
                        "reason": "missing_core_measurements",
                        "missing_core_metrics": row["missing_core_metrics"],
                    }
                ),
            }
            if row["loc_id"] in model_index:
                index = model_index[row["loc_id"]]
                feature_values["model_z_scores"] = {
                    field: float(scaled_matrix[index, position]) for position, field in enumerate(active_model_features)
                }

            conflict_target = "(zone_id, observed_at)" if is_legacy_zone else "(cell_id, observed_at)"
            feature_id = db.execute(
                text(
                    f"""
                    INSERT INTO engineered_features (
                        zone_id, cell_id, environment_data_id, observed_at,
                        pollution_risk_score, heat_stress_score, water_stress_score, vegetation_stress_score,
                        feature_values
                    ) VALUES (
                        :zone_id, :cell_id, :environment_data_id, :observed_at,
                        :pollution, :heat, :moisture, :vegetation, CAST(:feature_values AS jsonb)
                    )
                    ON CONFLICT {conflict_target} DO UPDATE SET
                        environment_data_id = EXCLUDED.environment_data_id,
                        pollution_risk_score = EXCLUDED.pollution_risk_score,
                        heat_stress_score = EXCLUDED.heat_stress_score,
                        water_stress_score = EXCLUDED.water_stress_score,
                        vegetation_stress_score = EXCLUDED.vegetation_stress_score,
                        feature_values = EXCLUDED.feature_values
                    RETURNING id
                    """
                ),
                {
                    "zone_id": row["loc_id"],
                    "environment_data_id": row["environment_data_id"],
                    "observed_at": snapshot_at,
                    "pollution": relative_stress["pollution"],
                    "heat": relative_stress["heat"],
                    "moisture": relative_stress["moisture"],
                    "vegetation": relative_stress["vegetation"],
                    "feature_values": json.dumps(feature_values, default=_as_json_value),
                },
            ).scalar_one()
            engineered_feature_ids[row["loc_id"]] = int(feature_id)
            feature_value_records[row["loc_id"]] = feature_values

        anomaly_count = 0
        score_values = [float(value) for value in raw_anomaly_scores]
        for index, row in enumerate(eligible_rows):
            is_anomaly = bool(predictions[index] == -1)
            anomaly_count += int(is_anomaly)
            zscores = {
                field: float(scaled_matrix[index, position]) for position, field in enumerate(active_model_features)
            }
            dominant = _dominant_deviations(zscores, row["values"], active_model_features)
            aqi_source = row["sources"]["aqi"]
            temporal_context = temporal_contexts[row["loc_id"]]
            temporal_context["spatial_anomaly_persistence"] = finalize_anomaly_persistence(
                temporal_context["spatial_anomaly_persistence"],
                is_anomaly,
            )
            feature_value_records[row["loc_id"]]["temporal_context"] = temporal_context
            db.execute(
                text(
                    """
                    UPDATE engineered_features
                    SET feature_values = CAST(:feature_values AS jsonb)
                    WHERE id = :feature_id
                    """
                ),
                {
                    "feature_id": engineered_feature_ids[row["loc_id"]],
                    "feature_values": json.dumps(feature_value_records[row["loc_id"]], default=_as_json_value),
                },
            )
            evidence = {
                "schema_version": "1.0",
                "snapshot_date": selected_date.isoformat(),
                "model": {
                    "name": MODEL_NAME,
                    "library": "scikit-learn",
                    "library_version": sklearn_version,
                    "random_state": MODEL_RANDOM_STATE,
                    "n_estimators": MODEL_ESTIMATORS,
                    "contamination": MODEL_CONTAMINATION,
                    "feature_order": list(active_model_features),
                    "excluded_constant_features": list(excluded_constant_features),
                    "score_definition": "negative sklearn score_samples; higher values are more anomalous",
                },
                "raw_values": row["values"],
                "feature_z_scores": zscores,
                "dominant_deviations": dominant,
                "aqi_provenance": {
                    "source_type": aqi_source.get("aqi_source_type"),
                    "nearest_station_distance_m": _as_json_value(aqi_source.get("aqi_nearest_station_distance_m")),
                },
                "source_records": {
                    field: {
                        "environment_data_id": source["environment_data_id"],
                        "observed_at": source["observed_at"].isoformat(),
                    }
                    for field, source in row["sources"].items()
                },
                "temporal_context": temporal_context,
            }
            top = ", ".join(
                f"{item['label']} {item['direction']} Mumbai snapshot baseline ({item['z_score']:+.2f}σ)"
                for item in dominant[:2]
            )
            root_cause = f"Spatial multivariate outlier evidence: {top}." if is_anomaly else None
            db.execute(
                text(
                    """
                    INSERT INTO anomaly_results (
                        zone_id, environment_data_id, engineered_feature_id, observed_at, detected_at,
                        anomaly_score, is_anomaly, model_name, anomaly_type, root_cause, mitigation_suggestion, evidence
                    ) VALUES (
                        :zone_id, :environment_data_id, :engineered_feature_id, :observed_at, :detected_at,
                        :anomaly_score, :is_anomaly, :model_name, :anomaly_type, :root_cause, NULL, CAST(:evidence AS jsonb)
                    )
                    ON CONFLICT (zone_id, observed_at, model_name, is_legacy_zone=is_legacy_zone) DO UPDATE SET
                        environment_data_id = EXCLUDED.environment_data_id,
                        engineered_feature_id = EXCLUDED.engineered_feature_id,
                        detected_at = EXCLUDED.detected_at,
                        anomaly_score = EXCLUDED.anomaly_score,
                        is_anomaly = EXCLUDED.is_anomaly,
                        anomaly_type = EXCLUDED.anomaly_type,
                        root_cause = EXCLUDED.root_cause,
                        mitigation_suggestion = EXCLUDED.mitigation_suggestion,
                        evidence = EXCLUDED.evidence
                    """
                ),
                {
                    "zone_id": row["loc_id"],
                    "environment_data_id": row["environment_data_id"],
                    "engineered_feature_id": engineered_feature_ids[row["loc_id"]],
                    "observed_at": snapshot_at,
                    "detected_at": datetime.now(timezone.utc),
                    "anomaly_score": score_values[index],
                    "is_anomaly": is_anomaly,
                    "model_name": MODEL_NAME,
                    "anomaly_type": "isolation_forest_spatial_anomaly" if is_anomaly else "isolation_forest_spatial_inlier",
                    "root_cause": root_cause,
                    "evidence": json.dumps(evidence, default=_as_json_value),
                },
            )

        db.commit()
        temporal_availability = {
            metric: {
                "current_metric_rows": sum(metric in context["metrics"] for context in temporal_contexts.values()),
                "previous_observation": sum(
                    bool(context["metrics"].get(metric, {}).get("availability", {}).get("previous_observation"))
                    for context in temporal_contexts.values()
                ),
                "baseline": sum(
                    bool(context["metrics"].get(metric, {}).get("availability", {}).get("baseline"))
                    for context in temporal_contexts.values()
                ),
                "trend": sum(
                    bool(context["metrics"].get(metric, {}).get("availability", {}).get("trend"))
                    for context in temporal_contexts.values()
                ),
            }
            for metric in MODEL_FEATURES
        }
        return {
            "snapshot_date": selected_date.isoformat(),
            "snapshot_at": snapshot_at.isoformat(),
            "zones_total": len(snapshot_rows),
            "feature_rows_upserted": len(snapshot_rows),
            "model_eligible_rows": len(eligible_rows),
            "excluded_missing_core_measurements": len(snapshot_rows) - len(eligible_rows),
            "anomaly_count": anomaly_count,
            "inlier_count": len(eligible_rows) - anomaly_count,
            "anomaly_score_min": min(score_values),
            "anomaly_score_max": max(score_values),
            "anomaly_score_mean": float(np.mean(score_values)),
            "model_feature_order": list(active_model_features),
            "excluded_constant_features": list(excluded_constant_features),
            "temporal_feature_availability": temporal_availability,
        }
