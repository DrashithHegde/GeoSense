"""Inspect bounds of zones in DB and find where the 2 Landsat images actually are."""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = REPO_ROOT / "server"
for p in (str(REPO_ROOT), str(SERVER_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import ee
from sqlalchemy import text
from app.database import get_db
from gee.gee_client import initialize_ee
from gee.ingest_lst import LST_DATASETS, fetch_zones_as_fc


def inspect():
    initialize_ee()

    with get_db() as db:
        bounds = db.execute(text("""
            SELECT
                ST_XMin(ST_Extent(geometry)) as min_x,
                ST_YMin(ST_Extent(geometry)) as min_y,
                ST_XMax(ST_Extent(geometry)) as max_x,
                ST_YMax(ST_Extent(geometry)) as max_y
            FROM zones
        """)).mappings().one()
        print("Zones PostGIS BBox:")
        print(f"  min_lon (X): {bounds['min_x']}")
        print(f"  min_lat (Y): {bounds['min_y']}")
        print(f"  max_lon (X): {bounds['max_x']}")
        print(f"  max_lat (Y): {bounds['max_y']}")

        # Test what GEE calculates as zones_fc.geometry()
        zones_fc = fetch_zones_as_fc(db)
        fc_geom_bounds = zones_fc.geometry().bounds().getInfo()
        print("\nzones_fc.geometry().bounds() in GEE:")
        print(fc_geom_bounds)

        # Now query L8/L9 with MUMBAI_BBOX from earlier vs fc_geom_bounds
        bbox_geom = ee.Geometry(fc_geom_bounds)
        l8_bbox = ee.ImageCollection(LST_DATASETS[0]).filterDate("2026-07-07", "2026-08-21").filterBounds(bbox_geom)
        print("L8 with fc_geom_bounds:", l8_bbox.size().getInfo())

        # What were the 2 images found with the manual MUMBAI_BBOX?
        manual_bbox = ee.Geometry.BBox(72.75, 18.85, 73.05, 19.30)
        l8_manual = ee.ImageCollection(LST_DATASETS[0]).filterDate("2026-07-07", "2026-08-21").filterBounds(manual_bbox)
        l9_manual = ee.ImageCollection(LST_DATASETS[1]).filterDate("2026-07-07", "2026-08-21").filterBounds(manual_bbox)
        merged_manual = l8_manual.merge(l9_manual)
        manual_count = merged_manual.size().getInfo()
        print("\nManual BBox count:", manual_count)
        if manual_count > 0:
            imgs = merged_manual.getInfo().get("features", [])
            for img in imgs:
                img_id = img["id"]
                img_geom = img.get("geometry")
                print(f"\nImage ID: {img_id}")
                # Check intersection of this image with zones_fc
                img_ee = ee.Image(img_id)
                intersects_fc = img_ee.geometry().intersects(zones_fc.geometry()).getInfo()
                print(f"  Intersects zones_fc: {intersects_fc}")
                intersects_bbox = img_ee.geometry().intersects(bbox_geom).getInfo()
                print(f"  Intersects bbox_geom: {intersects_bbox}")
                # Image footprint
                img_bounds = img_ee.geometry().bounds().getInfo()
                print(f"  Image bounds: {img_bounds}")


if __name__ == "__main__":
    inspect()
