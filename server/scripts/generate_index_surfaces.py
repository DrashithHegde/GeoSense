"""Generate the supporting NDMI GeoTIFF (Sentinel-2, 20 m) for the NDVI window; NDBI = -NDMI is derived.

Usage (from server/):  python scripts/generate_index_surfaces.py [--start YYYY-MM-DD --end YYYY-MM-DD]
Needs Earth Engine credentials (same as the NDVI surface). Writes data/surfaces/indices/*.tif
and adds "ndmi" / "ndbi" records to the manifest. They are not map layers.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
for p in (str(SERVER_ROOT.parent), str(SERVER_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.services.surfaces.index_surfaces import generate_index_surface, ndvi_window  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start")
    ap.add_argument("--end")
    a = ap.parse_args()
    win = (a.start, a.end) if a.start and a.end else ndvi_window()
    if not win:
        print("No NDVI window in the manifest; pass --start and --end.", file=sys.stderr)
        return 2
    out = {}
    rec = generate_index_surface("ndmi", start_date=win[0], end_date=win[1])
    out["ndmi"] = {k: rec[k] for k in ("geotiff_filename", "image_count", "valid_pixels", "statistics")}
    out["ndbi"] = "derived as -NDMI (same file, documented in the manifest)"
    print(json.dumps({"window": win, "indices": out}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
