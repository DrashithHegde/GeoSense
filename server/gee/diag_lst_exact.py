"""Detailed diagnosis of the 2 images in 2026-07-07 to 2026-08-21."""
import sys
from pathlib import Path
import json

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = REPO_ROOT / "server"
for p in (str(REPO_ROOT), str(SERVER_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import ee
from sqlalchemy import text
from app.database import get_db
from gee.gee_client import initialize_ee
from gee.ingest_lst import LST_DATASETS, mask_landsat_l2, add_lst_celsius, fetch_zones_as_fc


def diagnose():
    initialize_ee()
    start_date = "2026-07-07"
    end_date = "2026-08-21"

    with get_db() as db:
        zones_fc = fetch_zones_as_fc(db)
        print("Zones FC count:", zones_fc.size().getInfo())

        l8 = (
            ee.ImageCollection(LST_DATASETS[0])
            .filterDate(start_date, end_date)
            .filterBounds(zones_fc.geometry())
        )
        l9 = (
            ee.ImageCollection(LST_DATASETS[1])
            .filterDate(start_date, end_date)
            .filterBounds(zones_fc.geometry())
        )
        merged = l8.merge(l9)
        image_count = int(merged.size().getInfo())
        print(f"Image count with zones_fc.geometry(): {image_count}")

        # List image IDs and metadata
        image_list = merged.toList(image_count).getInfo()
        for idx, img in enumerate(image_list):
            img_id = img["id"]
            props = img.get("properties", {})
            cloud_cover = props.get("CLOUD_COVER")
            cloud_land = props.get("CLOUD_COVER_LAND")
            date_acq = props.get("DATE_ACQUIRED")
            print(f"\nImage {idx+1}: {img_id}")
            print(f"  Acquired: {date_acq}")
            print(f"  Cloud Cover: {cloud_cover}%")
            print(f"  Cloud Cover Land: {cloud_land}%")

        # Now test masking on these images
        processed_coll = merged.map(mask_landsat_l2).map(add_lst_celsius)
        composite = processed_coll.median()
        band_names = composite.bandNames().getInfo()
        print(f"\nComposite band names: {band_names}")

        # Test reduceRegions on a small sample of zones
        sample_fc = zones_fc.limit(5)
        reduced = composite.select(["LST"]).reduceRegions(
            collection=sample_fc,
            reducer=ee.Reducer.mean(),
            scale=30,
        )
        feats = reduced.getInfo().get("features", [])
        print("\nSample reduceRegions output for 5 zones:")
        for f in feats:
            print("  Zone:", f.get("properties", {}).get("zone_id"), "Properties:", f.get("properties"))


if __name__ == "__main__":
    diagnose()
