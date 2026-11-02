import pathlib
import re

path = pathlib.Path("app/services/temporal_features.py")
text = path.read_text(encoding="utf-8")

# Refactor temporal_features.py to support both cell_id and zone_id dynamically.
# By default, functions will use cell_id.

text = text.replace("def _metric_context_from_raw(db, *, zone_id: int, metric: str, current: dict[str, Any])", "def _metric_context_from_raw(db, *, loc_id: int, metric: str, current: dict[str, Any], is_legacy_zone: bool = False)")
text = text.replace("EnvironmentData.zone_id == zone_id", "(EnvironmentData.zone_id == loc_id if is_legacy_zone else EnvironmentData.cell_id == loc_id)")

text = text.replace("def prior_anomaly_persistence(db, *, zone_id: int, snapshot_at: datetime, model_name: str)", "def prior_anomaly_persistence(db, *, loc_id: int, snapshot_at: datetime, model_name: str, is_legacy_zone: bool = False)")
text = text.replace("AnomalyResult.zone_id == zone_id", "(AnomalyResult.zone_id == loc_id if is_legacy_zone else AnomalyResult.cell_id == loc_id)")

text = text.replace("def build_temporal_contexts(db, snapshot_rows: list[dict[str, Any]], snapshot_at: datetime, model_name: str)", "def build_temporal_contexts(db, snapshot_rows: list[dict[str, Any]], snapshot_at: datetime, model_name: str, is_legacy_zone: bool = False)")
text = text.replace("zone_id=row[\"zone_id\"],", "loc_id=row[\"loc_id\"], is_legacy_zone=is_legacy_zone,")
text = text.replace("contexts[row[\"zone_id\"]] =", "contexts[row[\"loc_id\"]] =")

path.write_text(text, encoding="utf-8")
print("temporal_features.py patched")
