"""Delete map files that the city's manifest no longer uses (older renders and runs).

    python scripts/prune_surfaces.py --city mumbai --dry-run     # list only
    python scripts/prune_surfaces.py --city mumbai               # delete
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT))

from app.services.surfaces.housekeeping import prune_unreferenced  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    removed = prune_unreferenced(keep_recent_s=0, dry_run=a.dry_run)
    total = sum(f.stat().st_size for f in removed if f.exists()) if a.dry_run else None
    for f in removed:
        print(("would delete " if a.dry_run else "deleted ") + str(f))
    print(f"{len(removed)} file(s)" + (f", {total / 1e6:.1f} MB" if total is not None else ""))
    return 0


if __name__ == "__main__":
    from app.core.cities import run_script_for_city  # noqa: E402
    raise SystemExit(run_script_for_city(main))
