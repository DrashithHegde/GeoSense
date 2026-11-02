import pathlib
import re

path = pathlib.Path("app/services/feature_anomaly_pipeline.py")
text = path.read_text(encoding="utf-8")

# Refactor feature_anomaly_pipeline.py for loc_id support
text = text.replace("def _load_snapshot(db, snapshot_date: date)", "def _load_snapshot(db, snapshot_date: date, is_legacy_zone: bool = False)")
text = text.replace('''    zones = {
        row.id: {"zone_id": row.id, "zone_name": row.name}
        for row in db.execute(select(Zone.id, Zone.name).order_by(Zone.id))
    }''', '''    if is_legacy_zone:
        locations = {
            row.id: {"loc_id": row.id, "location_name": row.name}
            for row in db.execute(select(Zone.id, Zone.name).order_by(Zone.id))
        }
    else:
        from app.models import SpatialCell
        locations = {
            row.id: {"loc_id": row.id, "location_name": row.municipality_name}
            for row in db.execute(select(SpatialCell.id, SpatialCell.municipality_name).order_by(SpatialCell.id))
        }''')
text = text.replace("EnvironmentData.zone_id,", "EnvironmentData.zone_id if is_legacy_zone else EnvironmentData.cell_id,")

# Replace zone_id handling in the row loop
text = text.replace("selected[row[\"zone_id\"]][field] =", "selected[row[1]][field] =")
text = text.replace("for zone_id, zone in zones.items():", "for loc_id, loc in locations.items():")
text = text.replace("metric_sources = selected.get(zone_id, {})", "metric_sources = selected.get(loc_id, {})")
text = text.replace("**zone,", "**loc,")
text = text.replace('''        # During migration: only process zone-keyed rows; cell-only rows (zone_id IS NULL) are excluded.
        .where(EnvironmentData.zone_id.isnot(None))''', '''        .where((EnvironmentData.zone_id.isnot(None)) if is_legacy_zone else (EnvironmentData.cell_id.isnot(None)))''')

text = text.replace("def _find_snapshot_date(db)", "def _find_snapshot_date(db, is_legacy_zone: bool = False)")
text = text.replace("_load_snapshot(db, candidate)", "_load_snapshot(db, candidate, is_legacy_zone=is_legacy_zone)")
text = text.replace("def run_feature_anomaly_pipeline(snapshot_date: date | None = None)", "def run_feature_anomaly_pipeline(snapshot_date: date | None = None, is_legacy_zone: bool = False)")
text = text.replace("_find_snapshot_date(db)", "_find_snapshot_date(db, is_legacy_zone=is_legacy_zone)")
text = text.replace("_load_snapshot(db, selected_date)", "_load_snapshot(db, selected_date, is_legacy_zone=is_legacy_zone)")

text = text.replace('affected_zones = sorted({eligible_rows[index]["zone_id"] for index in np.where(invalid)[0]})', 'affected_locs = sorted({eligible_rows[index]["loc_id"] for index in np.where(invalid)[0]})')
text = text.replace('f"{affected_zones};', 'f"{affected_locs};')
text = text.replace('model_name)', 'model_name, is_legacy_zone=is_legacy_zone)')
text = text.replace('model_index = {row["zone_id"]: index for index, row in enumerate(eligible_rows)}', 'model_index = {row["loc_id"]: index for index, row in enumerate(eligible_rows)}')
text = text.replace('engineered_feature_ids[row["zone_id"]] = int(feature_id)', 'engineered_feature_ids[row["loc_id"]] = int(feature_id)')
text = text.replace('feature_value_records[row["zone_id"]] = feature_values', 'feature_value_records[row["loc_id"]] = feature_values')
text = text.replace('feature_value_records[row["zone_id"]]["temporal_context"] = temporal_context', 'feature_value_records[row["loc_id"]]["temporal_context"] = temporal_context')
text = text.replace('engineered_feature_ids[row["zone_id"]],', 'engineered_feature_ids[row["loc_id"]],')
text = text.replace('feature_value_records[row["zone_id"]]', 'feature_value_records[row["loc_id"]]')
text = text.replace('row["zone_id"]', 'row["loc_id"]')
text = text.replace('row["zone_id"],', 'row["loc_id"],')

text = text.replace('zone_id=row["loc_id"],', 'zone_id=row["loc_id"] if is_legacy_zone else None, cell_id=None if is_legacy_zone else row["loc_id"],')
text = text.replace('''                    INSERT INTO engineered_features (
                        zone_id, environment_data_id, observed_at,
                        pollution_risk_score, heat_stress_score, water_stress_score, vegetation_stress_score,
                        feature_values
                    ) VALUES (
                        :zone_id, :environment_data_id, :observed_at,
                        :pollution, :heat, :moisture, :vegetation, CAST(:feature_values AS jsonb)
                    )
                    ON CONFLICT (zone_id, observed_at) DO UPDATE SET''', 
                    '''                    INSERT INTO engineered_features (
                        zone_id, cell_id, environment_data_id, observed_at,
                        pollution_risk_score, heat_stress_score, water_stress_score, vegetation_stress_score,
                        feature_values
                    ) VALUES (
                        :zone_id, :cell_id, :environment_data_id, :observed_at,
                        :pollution, :heat, :moisture, :vegetation, CAST(:feature_values AS jsonb)
                    )
                    ON CONFLICT (zone_id, observed_at) WHERE zone_id IS NOT NULL DO UPDATE SET
                        environment_data_id = EXCLUDED.environment_data_id,
                        pollution_risk_score = EXCLUDED.pollution_risk_score,
                        heat_stress_score = EXCLUDED.heat_stress_score,
                        water_stress_score = EXCLUDED.water_stress_score,
                        vegetation_stress_score = EXCLUDED.vegetation_stress_score,
                        feature_values = EXCLUDED.feature_values
                    ON CONFLICT (cell_id, observed_at) WHERE cell_id IS NOT NULL DO UPDATE SET''')

text = text.replace('''                    INSERT INTO anomaly_results (
                        zone_id, environment_data_id, engineered_feature_id, observed_at, detected_at,
                        anomaly_score, is_anomaly, model_name, anomaly_type, root_cause, mitigation_suggestion, evidence
                    ) VALUES (
                        :zone_id, :environment_data_id, :engineered_feature_id, :observed_at, :detected_at,
                        :anomaly_score, :is_anomaly, :model_name, :anomaly_type, :root_cause, NULL, CAST(:evidence AS jsonb)
                    )
                    ON CONFLICT (zone_id, observed_at, model_name) DO UPDATE SET''',
                    '''                    INSERT INTO anomaly_results (
                        zone_id, cell_id, environment_data_id, engineered_feature_id, observed_at, detected_at,
                        anomaly_score, is_anomaly, model_name, anomaly_type, root_cause, mitigation_suggestion, evidence
                    ) VALUES (
                        :zone_id, :cell_id, :environment_data_id, :engineered_feature_id, :observed_at, :detected_at,
                        :anomaly_score, :is_anomaly, :model_name, :anomaly_type, :root_cause, NULL, CAST(:evidence AS jsonb)
                    )
                    ON CONFLICT (zone_id, observed_at, model_name) WHERE zone_id IS NOT NULL DO UPDATE SET
                        environment_data_id = EXCLUDED.environment_data_id,
                        engineered_feature_id = EXCLUDED.engineered_feature_id,
                        detected_at = EXCLUDED.detected_at,
                        anomaly_score = EXCLUDED.anomaly_score,
                        is_anomaly = EXCLUDED.is_anomaly,
                        anomaly_type = EXCLUDED.anomaly_type,
                        root_cause = EXCLUDED.root_cause,
                        mitigation_suggestion = EXCLUDED.mitigation_suggestion,
                        evidence = EXCLUDED.evidence
                    ON CONFLICT (cell_id, observed_at, model_name) WHERE cell_id IS NOT NULL DO UPDATE SET''')

path.write_text(text, encoding="utf-8")
print("feature_anomaly_pipeline.py patched")
