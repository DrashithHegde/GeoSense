"""Minimal GEE test script for GeoSense.

Run from the repository root with:

    python -m server.gee.test_gee

This script will attempt to initialize Earth Engine (service account if
`GOOGLE_APPLICATION_CREDENTIALS` is set, otherwise default auth) and then
perform a small metadata/query operation on a public dataset.
"""
from __future__ import annotations

import logging
import sys

from . import initialize_ee, is_initialized
import ee

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    try:
        initialize_ee()
    except Exception as e:
        logger.error("Initialization failed: %s", e)
        return 2

    # Proceed to a small test query; initialization may succeed even if
    # a lightweight 'is_initialized' probe fails in some environments.

    try:
        # Small metadata query: count images in a tiny Sentinel-2 collection slice
        # Use a time window and a small bounding box near Mumbai. We only request the size.
        bbox = ee.Geometry.Rectangle([72.85, 19.0, 72.86, 19.01])
        coll = ee.ImageCollection("COPERNICUS/S2_SR") \
            .filterBounds(bbox) \
            .filterDate("2024-01-01", "2024-01-15")

        count = coll.size().getInfo()
        logger.info("Successfully queried Earth Engine. Image count (small window): %s", count)
        logger.info("GEE test succeeded — Earth Engine accessible from Python.")
        return 0
    except Exception as e:
        logger.error("GEE query failed: %s", e)
        return 4


if __name__ == "__main__":
    sys.exit(main())
