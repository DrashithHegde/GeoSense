import pathlib
import re

path = pathlib.Path("app/services/feature_anomaly_pipeline.py")
text = path.read_text(encoding="utf-8")

# Fix SQL statements to switch dynamically
text = text.replace('''                    INSERT INTO engineered_features (
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
                    ON CONFLICT (cell_id, observed_at) WHERE cell_id IS NOT NULL DO UPDATE SET''',
'''                    INSERT INTO engineered_features (
                        zone_id, cell_id, environment_data_id, observed_at,
                        pollution_risk_score, heat_stress_score, water_stress_score, vegetation_stress_score,
                        feature_values
                    ) VALUES (
                        :zone_id, :cell_id, :environment_data_id, :observed_at,
                        :pollution, :heat, :moisture, :vegetation, CAST(:feature_values AS jsonb)
                    )
                    ON CONFLICT (zone_id, observed_at) DO UPDATE SET'''
)

text = text.replace('''                    INSERT INTO anomaly_results (
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
                    ON CONFLICT (cell_id, observed_at, model_name) WHERE cell_id IS NOT NULL DO UPDATE SET''',
'''                    INSERT INTO anomaly_results (
                        zone_id, cell_id, environment_data_id, engineered_feature_id, observed_at, detected_at,
                        anomaly_score, is_anomaly, model_name, anomaly_type, root_cause, mitigation_suggestion, evidence
                    ) VALUES (
                        :zone_id, :cell_id, :environment_data_id, :engineered_feature_id, :observed_at, :detected_at,
                        :anomaly_score, :is_anomaly, :model_name, :anomaly_type, :root_cause, NULL, CAST(:evidence AS jsonb)
                    )
                    ON CONFLICT (zone_id, observed_at, model_name) DO UPDATE SET'''
)

# Replace the static SQL with dynamic generation
text = text.replace('''            feature_id = db.execute(
                text(
                    """
                    INSERT INTO engineered_features (
                        zone_id, cell_id, environment_data_id, observed_at,
                        pollution_risk_score, heat_stress_score, water_stress_score, vegetation_stress_score,
                        feature_values
                    ) VALUES (
                        :zone_id, :cell_id, :environment_data_id, :observed_at,
                        :pollution, :heat, :moisture, :vegetation, CAST(:feature_values AS jsonb)
                    )
                    ON CONFLICT (zone_id, observed_at) DO UPDATE SET
                        environment_data_id = EXCLUDED.environment_data_id,
                        pollution_risk_score = EXCLUDED.pollution_risk_score,
                        heat_stress_score = EXCLUDED.heat_stress_score,
                        water_stress_score = EXCLUDED.water_stress_score,
                        vegetation_stress_score = EXCLUDED.vegetation_stress_score,
                        feature_values = EXCLUDED.feature_values
                    RETURNING id
                    """
                ),''',
'''            conflict_target = "(zone_id, observed_at)" if is_legacy_zone else "(cell_id, observed_at)"
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
                ),'''
)

text = text.replace('''            db.execute(
                text(
                    """
                    INSERT INTO anomaly_results (
                        zone_id, cell_id, environment_data_id, engineered_feature_id, observed_at, detected_at,
                        anomaly_score, is_anomaly, model_name, anomaly_type, root_cause, mitigation_suggestion, evidence
                    ) VALUES (
                        :zone_id, :cell_id, :environment_data_id, :engineered_feature_id, :observed_at, :detected_at,
                        :anomaly_score, :is_anomaly, :model_name, :anomaly_type, :root_cause, NULL, CAST(:evidence AS jsonb)
                    )
                    ON CONFLICT (zone_id, observed_at, model_name) DO UPDATE SET
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
                ),''',
'''            anomaly_conflict_target = "(zone_id, observed_at, model_name)" if is_legacy_zone else "(cell_id, observed_at, model_name)"
            db.execute(
                text(
                    f"""
                    INSERT INTO anomaly_results (
                        zone_id, cell_id, environment_data_id, engineered_feature_id, observed_at, detected_at,
                        anomaly_score, is_anomaly, model_name, anomaly_type, root_cause, mitigation_suggestion, evidence
                    ) VALUES (
                        :zone_id, :cell_id, :environment_data_id, :engineered_feature_id, :observed_at, :detected_at,
                        :anomaly_score, :is_anomaly, :model_name, :anomaly_type, :root_cause, NULL, CAST(:evidence AS jsonb)
                    )
                    ON CONFLICT {anomaly_conflict_target} DO UPDATE SET
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
                ),'''
)

path.write_text(text, encoding="utf-8")
print("feature_anomaly_pipeline.py SQL patched")
