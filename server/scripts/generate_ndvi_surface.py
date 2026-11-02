"""Generate a real current-window Sentinel-2 NDVI surface without DB writes."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

SERVER_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVER_ROOT.parent
for path in (str(REPO_ROOT), str(SERVER_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from app.services.surfaces.ndvi_surface import generate_ndvi_surface
from gee.ingest_ndvi_ndwi import COMPOSITE_WINDOW_DAYS


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate GeoSense's real Sentinel-2 NDVI surface")
    parser.add_argument("--end", help="UTC composite end date (YYYY-MM-DD)")
    parser.add_argument("--start", help="UTC composite start date (YYYY-MM-DD)")
    args = parser.parse_args()
    end = datetime.fromisoformat(args.end).date() if args.end else datetime.now(timezone.utc).date()
    start = datetime.fromisoformat(args.start).date() if args.start else end - timedelta(days=COMPOSITE_WINDOW_DAYS)
    report = generate_ndvi_surface(start_date=start.isoformat(), end_date=end.isoformat())
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
