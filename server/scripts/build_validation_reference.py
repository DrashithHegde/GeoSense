"""Independent ground-truth reference: ESA WorldCover 10 m (2021, v200) class shares per cell.

WorldCover is produced independently of GeoSense (different method, different team), so
comparing our NDVI/MNDWI/NDBI-based shares and our LST patterns with it is a real check, not a
circular one. Writes data/validation/worldcover_cells_v200.csv (+ .json metadata).

    python scripts/build_validation_reference.py          (needs Earth Engine credentials)
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
for p in (str(SERVER_ROOT.parent), str(SERVER_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.services.ml.validation import WORLDCOVER_CLASSES, WORLDCOVER_CSV  # noqa: E402


def main() -> int:
    import ee

    from app.database import SessionLocal
    from gee.cell_reducer import load_cell_polygons, reduce_cells
    from gee.gee_client import initialize_ee

    initialize_ee()
    wc = ee.ImageCollection("ESA/WorldCover/v200").first().select("Map")
    onehot = ee.Image.cat([wc.eq(code).rename(name) for code, name in WORLDCOVER_CLASSES.items()])
    db = SessionLocal()
    try:
        cells = load_cell_polygons(db)
    finally:
        db.close()
    rows = reduce_cells(onehot, ee.Reducer.mean(), 10, cells, label="WorldCover")
    WORLDCOVER_CSV.parent.mkdir(parents=True, exist_ok=True)
    cols = ["cell_id"] + [f"wc_{n}" for n in WORLDCOVER_CLASSES.values()]
    with WORLDCOVER_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([r["cell_id"]] + [r.get(n) for n in WORLDCOVER_CLASSES.values()])
    WORLDCOVER_CSV.with_suffix(".json").write_text(json.dumps({
        "dataset": "ESA/WorldCover/v200 (2021), 10 m",
        "citation": "Zanaga, D. et al. (2022). ESA WorldCover 10 m 2021 v200. Zenodo. https://doi.org/10.5281/zenodo.7254221",
        "method": "share of each class's 10 m pixels inside each 300 m cell (Earth Engine reduceRegions, mean of one-hot bands)",
        "cells": len(rows), "generated_at": datetime.now(timezone.utc).isoformat()}, indent=2), encoding="utf-8")
    print(f"WorldCover shares written for {len(rows)} cells -> {WORLDCOVER_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
