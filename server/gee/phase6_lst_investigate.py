"""Phase 6 — Task A: Read-only Landsat LST availability investigation via Earth Engine.

This script does NOT write anything to the database. It only queries GEE.

Checks:
1. Raw image count: L8 + L9, no filters, Mumbai bbox
2. Image count: after filterDate only
3. Image count: after filterDate + filterBounds
4. Image count: after QA_PIXEL masking
5. Band availability: does ST_B10 exist on available images?
6. Composite: does LST produce valid values after masking?
7. Alternative window: try a longer window to find *any* Landsat imagery
8. Collection sanity: try 2026-06-01 to 2026-08-21 (more generous window)
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = REPO_ROOT / "server"
for p in (str(REPO_ROOT), str(SERVER_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import ee
from gee.gee_client import initialize_ee

LANDSAT_COLLECTIONS = [
    "LANDSAT/LC08/C02/T1_L2",   # Landsat 8
    "LANDSAT/LC09/C02/T1_L2",   # Landsat 9
]

# The window that returned 0 images
FAILED_START = "2026-07-07"
FAILED_END   = "2026-08-21"

# Generous diagnostic window
LONG_START   = "2026-06-01"
LONG_END     = "2026-08-21"

# Even longer: look back 6 months
VERY_LONG_START = "2026-02-01"
VERY_LONG_END   = "2026-08-21"


def count(collection: ee.ImageCollection) -> int:
    return int(collection.size().getInfo())


def run():
    print("Initializing Earth Engine ...")
    initialize_ee()
    print("EE initialized.\n")
    MUMBAI_BBOX = ee.Geometry.BBox(72.75, 18.85, 73.05, 19.30)

    for col_id in LANDSAT_COLLECTIONS:
        short_name = col_id.split("/")[-1]
        print(f"=== {col_id} ===")

        # 1. No filters at all — is the collection accessible?
        try:
            base = ee.ImageCollection(col_id)
            # We won't count all images (too slow), just probe one
            first = base.first()
            first_id = first.id().getInfo()
            print(f"  Collection accessible. First image ID: {first_id}")
        except Exception as ex:
            print(f"  ERROR accessing collection: {ex}")
            continue

        # 2. filterDate only (no bounds) — how many images in failed window?
        try:
            n_date = count(ee.ImageCollection(col_id).filterDate(FAILED_START, FAILED_END))
            print(f"  filterDate({FAILED_START} -> {FAILED_END}) only: {n_date} images")
        except Exception as ex:
            print(f"  filterDate failed: {ex}")

        # 3. filterDate + filterBounds (Mumbai bbox) — the original logic
        try:
            n_bounds = count(
                ee.ImageCollection(col_id)
                .filterDate(FAILED_START, FAILED_END)
                .filterBounds(MUMBAI_BBOX)
            )
            print(f"  filterDate + filterBounds (Mumbai): {n_bounds} images")
        except Exception as ex:
            print(f"  filterDate+filterBounds failed: {ex}")

        # 4. Longer window: June 1 to Aug 21
        try:
            n_long = count(
                ee.ImageCollection(col_id)
                .filterDate(LONG_START, LONG_END)
                .filterBounds(MUMBAI_BBOX)
            )
            print(f"  filterDate({LONG_START} -> {LONG_END}) + filterBounds: {n_long} images")
        except Exception as ex:
            print(f"  Long window failed: {ex}")

        # 5. Very long window: Feb 1 to Aug 21
        try:
            n_vlong = count(
                ee.ImageCollection(col_id)
                .filterDate(VERY_LONG_START, VERY_LONG_END)
                .filterBounds(MUMBAI_BBOX)
            )
            print(f"  filterDate({VERY_LONG_START} -> {VERY_LONG_END}) + filterBounds: {n_vlong} images")
        except Exception as ex:
            print(f"  Very long window failed: {ex}")

        # 6. For long window, check bands and cloud fraction on first image
        try:
            sample_img = (
                ee.ImageCollection(col_id)
                .filterDate(LONG_START, LONG_END)
                .filterBounds(MUMBAI_BBOX)
                .first()
            )
            band_names = sample_img.bandNames().getInfo()
            img_id = sample_img.id().getInfo()
            print(f"  Sample image (long window): {img_id}")
            print(f"  Bands: {band_names}")
            has_st_b10 = "ST_B10" in band_names
            has_qa_pixel = "QA_PIXEL" in band_names
            print(f"  ST_B10 present: {has_st_b10}")
            print(f"  QA_PIXEL present: {has_qa_pixel}")
        except Exception as ex:
            print(f"  Band probe failed: {ex}")

        print()

    # 7. Merged L8+L9 counts — what the ingest script actually uses
    print("=== MERGED L8+L9 (as ingest_lst.py does) ===")
    for start, end, label in [
        (FAILED_START, FAILED_END, "Failed window (45d)"),
        (LONG_START, LONG_END, "Long window (82d)"),
        (VERY_LONG_START, VERY_LONG_END, "Very long (202d)"),
    ]:
        try:
            l8 = ee.ImageCollection(LANDSAT_COLLECTIONS[0]).filterDate(start, end).filterBounds(MUMBAI_BBOX)
            l9 = ee.ImageCollection(LANDSAT_COLLECTIONS[1]).filterDate(start, end).filterBounds(MUMBAI_BBOX)
            merged = l8.merge(l9)
            n = count(merged)
            print(f"  {label}: {n} images total (L8+L9)")
        except Exception as ex:
            print(f"  Merge count failed ({label}): {ex}")

    print()

    # 8. Try applying the QA mask to see if masked images have valid pixels
    print("=== QA MASKING TEST (long window, merged) ===")
    try:
        def mask_landsat(image):
            qa = image.select("QA_PIXEL")
            clear = (
                qa.bitwiseAnd(1 << 0).eq(0)
                .And(qa.bitwiseAnd(1 << 3).eq(0))
                .And(qa.bitwiseAnd(1 << 4).eq(0))
            )
            return image.updateMask(clear)

        def add_lst_celsius(image):
            lst_c = image.select("ST_B10").multiply(0.00341802).add(149.0).subtract(273.15).rename("LST")
            return image.addBands(lst_c)

        l8 = ee.ImageCollection(LANDSAT_COLLECTIONS[0]).filterDate(LONG_START, LONG_END).filterBounds(MUMBAI_BBOX)
        l9 = ee.ImageCollection(LANDSAT_COLLECTIONS[1]).filterDate(LONG_START, LONG_END).filterBounds(MUMBAI_BBOX)
        merged = l8.merge(l9)
        n_before = count(merged)
        processed = merged.map(mask_landsat).map(add_lst_celsius)
        n_after = count(processed)  # count doesn't drop images, only pixels
        print(f"  Images before masking: {n_before}")
        print(f"  Images after mask+LST (collection size unchanged): {n_after}")

        if n_before > 0:
            # Try to compute median composite and sample one point
            composite = processed.median()
            sample_pt = ee.Geometry.Point([72.87, 19.07])  # ~central Mumbai
            sample_val = composite.select("LST").sample(region=sample_pt, scale=30, numPixels=1).first()
            try:
                sv = sample_val.getInfo()
                print(f"  LST sample at central Mumbai: {sv}")
            except Exception as ex:
                print(f"  LST sample failed (possibly all masked): {ex}")
    except Exception as ex:
        print(f"  QA masking test failed: {ex}")

    print()
    print("=== LST INVESTIGATION COMPLETE ===")


if __name__ == "__main__":
    run()
