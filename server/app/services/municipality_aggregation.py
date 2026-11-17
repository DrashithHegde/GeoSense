"""Municipality polygons of the current city with the mean of their 300 m cells.

Values are means over the cells' latest ML snapshot (engineered_features), the same numbers the
models were run on: NDVI, LST, Water Health (water cells only), CPCB AQI (where a station surface
existed) and the composite score. A municipality value is a summary for context, never a value
of any single place in it. NULL stays NULL.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.core.cities import current_city_id
from app.services.municipality_boundaries import load_municipality_boundaries

_SQL = text("""
    WITH latest AS (
        SELECT DISTINCT ON (ef.cell_id) ef.cell_id, ef.feature_values -> 'raw_values' AS f
        FROM engineered_features ef JOIN spatial_cells sc ON sc.id = ef.cell_id
        WHERE sc.city = :city
        ORDER BY ef.cell_id, ef.observed_at DESC, ef.id DESC
    )
    SELECT sc.municipality_name,
           count(sc.id)                                           AS cell_count,
           avg((l.f ->> 'ndvi_mean')::float)                      AS ndvi,
           avg((l.f ->> 'lst_mean')::float)                       AS lst,
           avg((l.f ->> 'wh_mean')::float)                        AS water_health_score,
           avg((l.f ->> 'aqi_idw')::float)                        AS aqi,
           avg((l.f ->> 'composite_cell')::float)                 AS composite
    FROM spatial_cells sc LEFT JOIN latest l ON l.cell_id = sc.id
    WHERE sc.city = :city AND sc.municipality_name IS NOT NULL
    GROUP BY sc.municipality_name
""")


def _f(v) -> float | None:
    return None if v is None else float(v)


def get_municipality_metrics(db) -> list[dict[str, Any]]:
    rows = {r["municipality_name"]: r for r in db.execute(_SQL, {"city": current_city_id()}).mappings().all()}
    out = []
    for muni in load_municipality_boundaries():
        d = rows.get(muni["name"]) or {}
        comp = _f(d.get("composite"))
        out.append({
            "id": muni["id"],
            "name": muni["name"],
            "geometry": muni["geojson"],
            "aqi": _f(d.get("aqi")),
            "ndvi": _f(d.get("ndvi")),
            "lst": _f(d.get("lst")),
            "water_health_score": _f(d.get("water_health_score")),
            # 0-100 (the composite surface is 0-1)
            "composite_score": None if comp is None else round(comp * 100.0, 1),
            "cell_count": int(d.get("cell_count") or 0),
        })
    return out
