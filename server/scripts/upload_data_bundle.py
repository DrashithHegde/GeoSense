"""Pack, validate, and upload the GeoSense data bundle to private Azure Blob Storage."""
from __future__ import annotations

import os
import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVER_ROOT.parent
sys.path.insert(0, str(SERVER_ROOT))

from app.core.cities import CITIES  # noqa: E402
from scripts.data_bundle import pack, publish_to_blob  # noqa: E402


def main() -> int:
    container = os.getenv("AZURE_STORAGE_CONTAINER", "geosense")
    archive = REPO_ROOT / "geosense-data.tar.gz"
    cities = [c for c in CITIES if (CITIES[c].data_dir / "surfaces" / "manifest.json").exists()] or ["mumbai"]
    rc = pack(archive, cities)
    if rc:
        return rc
    try:
        publish_to_blob(archive, container=container)
        return 0
    except Exception as exc:
        print(f"Blob publish failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
