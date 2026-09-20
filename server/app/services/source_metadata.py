"""Guards for source-specific processing context on raw observations."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import text


METADATA_METRIC_COLUMNS = {
    "aqi": ("aqi", "pm25", "pm10", "no2"),
    "ndvi_ndwi": ("ndvi", "ndwi"),
    "water_health": ("mndwi", "ndci", "turbidity_proxy", "water_extent_m2", "water_health_score"),
    "lst": ("lst",),
}


def metadata_payload(key: str, context: dict[str, Any] | None) -> str:
    """Serialize only context for a metric that is actually present in a row."""
    return json.dumps({key: context} if context else {})


def ensure_compatible_metadata(
    db,
    *,
    zone_id: int,
    observed_at: datetime,
    key: str,
    context: dict[str, Any] | None,
) -> None:
    """Reject a different interpretation of an existing zone/timestamp measurement.

    The existing unique key remains the record identity.  A re-run with the same
    source context is safe; attempting to reuse the timestamp with different
    source-window or processing parameters fails before the upsert.
    """
    if not context:
        return
    row = db.execute(
        text(
            """
                 SELECT source_metadata, aqi, pm25, pm10, no2, ndvi, ndwi, mndwi,
                     ndci, turbidity_proxy, water_extent_m2, water_health_score, lst
            FROM environment_data
            WHERE zone_id = :zone_id AND observed_at = :observed_at
            FOR UPDATE
            """
        ),
        {"zone_id": zone_id, "observed_at": observed_at},
    ).mappings().one_or_none()
    if not row:
        return
    existing = row["source_metadata"] or {}
    previous = existing.get(key) if isinstance(existing, dict) else None
    if previous is None and not existing:
        metric_columns = METADATA_METRIC_COLUMNS.get(key, ())
        if any(row[column] is not None for column in metric_columns):
            raise ValueError(
                f"Refusing to overwrite legacy zone {zone_id} at {observed_at.isoformat()}: "
                f"its existing {key} measurement has no source metadata"
            )
    if previous is not None and previous != context:
        raise ValueError(
            f"Refusing to overwrite zone {zone_id} at {observed_at.isoformat()} with a different {key} configuration"
        )
