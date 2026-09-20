"""Debug script to inspect reduceRegions properties for the current composite."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

import ee
from sqlalchemy import text

from app.database import get_db
from gee.gee_client import initialize_ee

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    initialize_ee()
    end = datetime.now().date()
    start = end - timedelta(days=14)
    start_str = start.isoformat()
    end_str = end.isoformat()

    with get_db() as db:
        sql = text("SELECT id, ST_AsGeoJSON(geometry) AS geojson FROM zones LIMIT 3;")
        res = db.execute(sql)
        feats = []
        for row in res:
            geom = json.loads(row[1])
            feats.append(ee.Feature(geom, {"zone_id": int(row[0])}))
        fc = ee.FeatureCollection(feats)

        coll = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterDate(start_str, end_str).filterBounds(fc.geometry())
        coll = coll.map(lambda i: i.updateMask(i.select('QA60').bitwiseAnd(1<<10).eq(0).And(i.select('QA60').bitwiseAnd(1<<11).eq(0))).addBands(i.normalizedDifference(['B8','B4']).rename('NDVI')).addBands(i.normalizedDifference(['B3','B8']).rename('NDWI')))
        composite = coll.median().select(['NDVI','NDWI'])
        reduced = composite.reduceRegions(collection=fc, reducer=ee.Reducer.mean(), scale=10)
        info = reduced.getInfo()
        logger.info("Features keys sample: %s", [list(f.get('properties',{}).keys()) for f in info.get('features', [])])


if __name__ == '__main__':
    main()
