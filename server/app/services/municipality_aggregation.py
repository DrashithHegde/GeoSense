"""
MMR Municipality metric aggregation using spatial_cells.
"""
from __future__ import annotations

import json
from shapely.geometry import shape
from sqlalchemy import text

from app.services.municipality_boundaries import load_municipality_boundaries

def get_municipality_metrics(db):
    from app.services.composite_score import calculate_composite
    boundaries = load_municipality_boundaries()

    # Pre-calculate cell metrics per municipality using the new spatial_cells grid
    sql = text("""
        WITH latest_aqi AS (
            SELECT DISTINCT ON (cell_id) cell_id, aqi FROM environment_data
            WHERE aqi IS NOT NULL AND cell_id IS NOT NULL
            ORDER BY cell_id, observed_at DESC, id DESC
        ), latest_ndvi AS (
            SELECT DISTINCT ON (cell_id) cell_id, ndvi FROM environment_data
            WHERE ndvi IS NOT NULL AND cell_id IS NOT NULL 
            ORDER BY cell_id, observed_at DESC, id DESC
        ), latest_lst AS (
            SELECT DISTINCT ON (cell_id) cell_id, lst FROM environment_data
            WHERE lst IS NOT NULL AND cell_id IS NOT NULL 
            ORDER BY cell_id, observed_at DESC, id DESC
        ), latest_water AS (
            SELECT DISTINCT ON (cell_id) cell_id, water_health_score FROM environment_data
            WHERE mndwi IS NOT NULL AND cell_id IS NOT NULL 
            ORDER BY cell_id, observed_at DESC, id DESC
        )
        SELECT 
            sc.municipality_name,
            AVG(aqi.aqi) as aqi,
            AVG(ndvi.ndvi) as ndvi,
            AVG(lst.lst) as lst,
            AVG(water.water_health_score) as water_health_score,
            COUNT(sc.id) as cell_count,
            MAX(sc.id) as rep_cell_id
        FROM spatial_cells sc
        LEFT JOIN latest_aqi   aqi   ON aqi.cell_id   = sc.id
        LEFT JOIN latest_ndvi  ndvi  ON ndvi.cell_id  = sc.id
        LEFT JOIN latest_lst   lst   ON lst.cell_id   = sc.id
        LEFT JOIN latest_water water ON water.cell_id = sc.id
        WHERE sc.municipality_name IS NOT NULL
        GROUP BY sc.municipality_name
    """)
    rows = db.execute(sql).mappings().all()
    
    muni_data = {r["municipality_name"]: r for r in rows}

    results = []
    for muni in boundaries:
        name = muni["name"]
        data = muni_data.get(name, {})
        
        # We compute composite in Python for consistency, using the averaged values
        aqi_val = data.get("aqi")
        ndvi_val = data.get("ndvi")
        lst_val = data.get("lst")
        wh_val = data.get("water_health_score")
        
        comp = calculate_composite(
            aqi=float(aqi_val) if aqi_val is not None else None,
            ndvi=float(ndvi_val) if ndvi_val is not None else None,
            lst=float(lst_val) if lst_val is not None else None,
            water_health_score=float(wh_val) if wh_val is not None else None
        )
        
        results.append({
            "id": muni["id"], 
            "name": name, 
            "geometry": muni["geojson"],
            "aqi": float(aqi_val) if aqi_val is not None else None,
            "ndvi": float(ndvi_val) if ndvi_val is not None else None,
            "lst": float(lst_val) if lst_val is not None else None,
            "water_health_score": float(wh_val) if wh_val is not None else None,
            "composite_score": comp.get("score") if comp else None,
            "zone_count": data.get("cell_count", 0),
            "representative_zone_id": data.get("rep_cell_id"),
        })

    return results
