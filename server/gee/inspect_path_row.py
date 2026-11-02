"""Inspect Landsat 8/9 acquisitions over Mumbai WRS-2 Path/Rows in 2026."""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = REPO_ROOT / "server"
for p in (str(REPO_ROOT), str(SERVER_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import ee
from gee.gee_client import initialize_ee
from gee.ingest_lst import LST_DATASETS


def inspect_path_row():
    initialize_ee()
    print("Querying Landsat scenes over Mumbai area (Path 148 Row 47 and Path 147 Row 47) in 2026...\n")

    for col_id in LST_DATASETS:
        col_name = col_id.split("/")[-1]
        print(f"=== {col_name} ===")
        coll = (
            ee.ImageCollection(col_id)
            .filterDate("2026-01-01", "2026-08-22")
            .filter(ee.Filter.inList("WRS_PATH", [147, 148]))
            .filter(ee.Filter.eq("WRS_ROW", 47))
        )
        size = coll.size().getInfo()
        print(f"Total scenes in 2026: {size}")
        if size > 0:
            features = coll.getInfo().get("features", [])
            for f in features:
                img_id = f["id"]
                props = f.get("properties", {})
                date_acq = props.get("DATE_ACQUIRED")
                cloud = props.get("CLOUD_COVER")
                path = props.get("WRS_PATH")
                row = props.get("WRS_ROW")
                print(f"  {img_id}: Date={date_acq}, Path={path}, Row={row}, Cloud={cloud}%")
        print()


if __name__ == "__main__":
    inspect_path_row()
