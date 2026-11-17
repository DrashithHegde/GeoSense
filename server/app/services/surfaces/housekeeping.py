"""Remove map files that no layer uses any more.

Every run of a layer writes new timestamped files (GeoTIFF + sharp/glow/halo images) and points
the manifest at them; the previous files are never read again. This removes, for the city in use,
files in the given surfaces folders that the manifest no longer references and that are older
than `keep_recent_s` (a browser that loaded the map a minute ago can still fetch them).

    python scripts/prune_surfaces.py --city mumbai [--dry-run]
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterable

from app.core.cities import city_path

SURFACES = city_path("surfaces")
FOLDERS = ("ndvi", "lst", "water-health", "aqi", "composite", "indices")
EXTENSIONS = (".tif", ".tiff", ".png", ".webp")


def referenced_files(manifest: dict) -> set[str]:
    """Base names of every file the manifest mentions."""
    names: set[str] = set()

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str) and o.lower().endswith(EXTENSIONS):
            names.add(Path(o.replace("\\", "/")).name)

    walk(manifest)
    return names


def prune_unreferenced(folders: Iterable[str] = FOLDERS, *, keep_recent_s: float = 2 * 3600,
                       dry_run: bool = False) -> list[Path]:
    root = Path(SURFACES)
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        return []
    keep = referenced_files(json.loads(manifest_path.read_text(encoding="utf-8")))
    now = time.time()
    removed = []
    for folder in folders:
        d = root / folder
        if not d.is_dir():
            continue
        for f in d.iterdir():
            if not f.is_file() or f.suffix.lower() not in EXTENSIONS or f.name in keep:
                continue
            if now - f.stat().st_mtime < keep_recent_s:
                continue
            removed.append(f)
            if not dry_run:
                f.unlink(missing_ok=True)
    # loose copies directly in surfaces/ (older runs wrote some there): every layer reads its files
    # from its own folder, so a root copy is unused when it is unreferenced or duplicated in a folder
    in_folders = {f.name for folder in FOLDERS if (root / folder).is_dir() for f in (root / folder).iterdir()}
    for f in root.iterdir():
        if not f.is_file() or f.suffix.lower() not in EXTENSIONS:
            continue
        if (f.name not in keep or f.name in in_folders) and now - f.stat().st_mtime >= keep_recent_s:
            removed.append(f)
            if not dry_run:
                f.unlink(missing_ok=True)
    return removed
