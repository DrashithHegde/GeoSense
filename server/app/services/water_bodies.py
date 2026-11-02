"""
OSM water body geometry service — READ-ONLY presentation layer.

Fetches actual water polygon geometries (rivers, lakes, reservoirs) from OSM
Overpass API for the MMR study area, then assigns Water Health scores from
overlapping analytical zones (SELECT-only against the DB).

Water bodies are real geographic shapes, NOT the analytical square grid cells.
NULL Water Health is never treated as healthy or converted to zero.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache

import requests
from shapely.geometry import Polygon, mapping, shape
from sqlalchemy import text

logger = logging.getLogger(__name__)

ZONE_BBOX    = (72.77, 18.89, 72.95, 19.22)
OVERPASS_URL = "https://overpass-api.de/api/interpreter"


@lru_cache(maxsize=1)
def _fetch_osm_water_bodies():
    """Fetch water body polygons from OSM Overpass. Cached for process lifetime."""
    minlat, minlon, maxlat, maxlon = ZONE_BBOX[1], ZONE_BBOX[0], ZONE_BBOX[3], ZONE_BBOX[2]
    query = f"""
[out:json][timeout:60];
(
  way["natural"="water"]({minlat},{minlon},{maxlat},{maxlon});
  way["water"]({minlat},{minlon},{maxlat},{maxlon});
  way["landuse"="reservoir"]({minlat},{minlon},{maxlat},{maxlon});
);
out geom;
"""
    try:
        resp = requests.post(OVERPASS_URL, data={"data": query}, timeout=70)
        resp.raise_for_status()
        elements = resp.json().get("elements", [])
        bodies = []
        for elem in elements:
            if elem.get("type") != "way":
                continue
            pts = elem.get("geometry", [])
            if len(pts) < 4:
                continue
            coords = [(pt["lon"], pt["lat"]) for pt in pts]
            try:
                poly = Polygon(coords)
                if not poly.is_valid:
                    poly = poly.buffer(0)
                if poly.is_empty or poly.area <= 0:
                    continue
                tags = elem.get("tags", {})
                name = tags.get("name") or tags.get("water", "Water Body")
                bodies.append({"id": f"w{elem['id']}", "name": name, "geom": poly})
            except Exception as exc:
                logger.debug("Skip way %s: %s", elem.get("id"), exc)
        logger.info("Fetched %d OSM water body polygons", len(bodies))
        return tuple(bodies)
    except Exception as exc:
        logger.error("Overpass water fetch failed: %s", exc)
        return tuple()


def get_water_bodies_with_health(db):
    """
    Return OSM water body polygons with Water Health scores from overlapping
    analytical zones. READ-ONLY. NULL scores remain NULL.
    """
    water_bodies = _fetch_osm_water_bodies()
    if not water_bodies:
        return []

    sql = text("""
        WITH latest_water AS (
            SELECT DISTINCT ON (zone_id) zone_id, water_health_score, water_health_status
            FROM environment_data
            WHERE mndwi IS NOT NULL
            ORDER BY zone_id, observed_at DESC, id DESC
        )
        SELECT z.id AS zone_id, ST_AsGeoJSON(z.geometry) AS geom_json,
               lw.water_health_score, lw.water_health_status
        FROM zones z
        JOIN latest_water lw ON lw.zone_id = z.id
    """)
    rows = db.execute(sql).mappings().all()

    water_zones = []
    for r in rows:
        if not r["geom_json"]:
            continue
        try:
            geom = shape(json.loads(r["geom_json"]))
        except Exception:
            continue
        water_zones.append({
            "geom": geom,
            "score": r["water_health_score"],
            "status": r["water_health_status"],
        })

    results = []
    for wb in water_bodies:
        wb_geom = wb["geom"]
        overlap_areas, score_pairs = [], []
        status = None

        for wz in water_zones:
            if not wb_geom.intersects(wz["geom"]):
                continue
            inter = wb_geom.intersection(wz["geom"])
            if inter.is_empty:
                continue
            area = inter.area
            overlap_areas.append(area)
            if wz["score"] is not None:
                score_pairs.append((wz["score"], area))
            if status is None:
                status = wz["status"]

        if not overlap_areas:
            continue  # completely outside analytical coverage — skip

        total_w  = sum(a for _, a in score_pairs)
        total_wv = sum(s * a for s, a in score_pairs)
        score_avg = (total_wv / total_w) if total_w > 0 else None

        results.append({
            "id":                  wb["id"],
            "name":                wb["name"],
            "geometry":            mapping(wb_geom),
            "water_health_score":  score_avg,   # None = unavailable, not zero
            "water_health_status": status,
        })

    return results
