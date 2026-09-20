"""
MMR Municipality metric aggregation — READ-ONLY presentation layer.
The 189 analytical zones, environment_data, engineered_features, anomaly_results
are NEVER modified. All DB access is SELECT-only.
"""
from __future__ import annotations

import json
from shapely.geometry import shape
from sqlalchemy import text

from app.services.municipality_boundaries import load_municipality_boundaries

def _weighted_avg(pairs):
    total_w, total_wv = 0.0, 0.0
    for val, w in pairs:
        if val is None or w <= 0.0:
            continue
        total_wv += val * w
        total_w  += w
    return total_wv / total_w if total_w > 0.0 else None


def get_municipality_metrics(db):
    from app.services.composite_score import calculate_composite
    boundaries = load_municipality_boundaries()

    sql = text("""
        WITH latest_aqi AS (
            SELECT DISTINCT ON (zone_id) zone_id, aqi FROM environment_data
            WHERE aqi IS NOT NULL
            ORDER BY zone_id,
                     CASE WHEN source_metadata->'aqi'->>'method' = 'station_discovery_idw' THEN 0 ELSE 1 END,
                     observed_at DESC, id DESC
        ), latest_ndvi AS (
            SELECT DISTINCT ON (zone_id) zone_id, ndvi FROM environment_data
            WHERE ndvi IS NOT NULL ORDER BY zone_id, observed_at DESC, id DESC
        ), latest_lst AS (
            SELECT DISTINCT ON (zone_id) zone_id, lst FROM environment_data
            WHERE lst IS NOT NULL ORDER BY zone_id, observed_at DESC, id DESC
        ), latest_water AS (
            SELECT DISTINCT ON (zone_id) zone_id, water_health_score FROM environment_data
            WHERE mndwi IS NOT NULL ORDER BY zone_id, observed_at DESC, id DESC
        )
        SELECT z.id AS zone_id, ST_AsGeoJSON(z.geometry) AS geom_json,
               aqi.aqi, ndvi.ndvi, lst.lst, water.water_health_score
        FROM zones z
        LEFT JOIN latest_aqi   aqi   ON aqi.zone_id   = z.id
        LEFT JOIN latest_ndvi  ndvi  ON ndvi.zone_id  = z.id
        LEFT JOIN latest_lst   lst   ON lst.zone_id   = z.id
        LEFT JOIN latest_water water ON water.zone_id = z.id
        ORDER BY z.id
    """)
    rows = db.execute(sql).mappings().all()

    zones = []
    for r in rows:
        if not r["geom_json"]:
            continue
        try:
            geom = shape(json.loads(r["geom_json"]))
        except Exception:
            continue
        comp = calculate_composite(aqi=r["aqi"], ndvi=r["ndvi"], lst=r["lst"],
                                   water_health_score=r["water_health_score"])
        zones.append({
            "zone_id": r["zone_id"], "geom": geom,
            "aqi": r["aqi"], "ndvi": r["ndvi"], "lst": r["lst"],
            "wh": r["water_health_score"],
            "composite": comp.get("score") if comp else None,
        })

    results = []
    for muni in boundaries:
        muni_geom = muni["shapely_geom"]
        aqi_p, ndvi_p, lst_p, wh_p, comp_p = [], [], [], [], []
        zone_count, best_rep_id, best_comp = 0, None, -1.0

        for z in zones:
            if not muni_geom.intersects(z["geom"]):
                continue
            inter = muni_geom.intersection(z["geom"])
            if inter.is_empty:
                continue
            area = inter.area
            zone_count += 1
            aqi_p.append((z["aqi"], area));   ndvi_p.append((z["ndvi"], area))
            lst_p.append((z["lst"], area));    wh_p.append((z["wh"], area))
            comp_p.append((z["composite"], area))
            cs = z["composite"] or 0.0
            if cs > best_comp:
                best_comp = cs; best_rep_id = z["zone_id"]

        results.append({
            "id": muni["id"], "name": muni["name"], "geometry": muni["geojson"],
            "aqi":                _weighted_avg(aqi_p),
            "ndvi":               _weighted_avg(ndvi_p),
            "lst":                _weighted_avg(lst_p),
            "water_health_score": _weighted_avg(wh_p),
            "composite_score":    _weighted_avg(comp_p),
            "zone_count":         zone_count,
            "representative_zone_id": best_rep_id,
        })

    return results
