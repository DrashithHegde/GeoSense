"""Pack / fetch the data a deployed GeoSense server needs (map layers, ML summaries, boundaries).

The large rasters are not built on the server (that needs Earth Engine), so they are packed on
your machine into one archive, uploaded once (Azure Blob Storage, a GitHub Release asset, any
HTTPS URL), and fetched by the server when it starts (DATA_BUNDLE_URL).

    python scripts/data_bundle.py pack                       # -> geosense-data.tar.gz (all cities)
    python scripts/data_bundle.py pack --out d.tar.gz --city delhi --city mumbai
    python scripts/data_bundle.py fetch                      # uses DATA_BUNDLE_URL (comma list = fallbacks)
    python scripts/data_bundle.py fetch --url https://.../geosense-data.tar.gz

Packed per city (only what the API reads): boundaries/*.geojson, surfaces/manifest.json and every
file it references, ml/ml_summary.json, history/{history_summary,change_if,seasons}.json.
Not packed: cell-feature CSVs, model files and history CSVs (pipeline outputs; the API reads the
database instead) and the RAG corpus (its vectors live in the database).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT))

from app.core.cities import CITIES, DATA_ROOT  # noqa: E402
from app.services.surfaces.housekeeping import referenced_files  # noqa: E402

MARKER = DATA_ROOT / ".bundle.json"
HISTORY_FILES = ("history_summary.json", "change_if.json", "seasons.json")


def _city_files(cid: str) -> list[Path]:
    city = CITIES[cid]
    d = city.data_dir
    files: list[Path] = sorted((d / "boundaries").glob("*.geojson"))
    manifest = d / "surfaces" / "manifest.json"
    if manifest.exists():
        files.append(manifest)
        names = referenced_files(json.loads(manifest.read_text(encoding="utf-8")))
        for f in (d / "surfaces").rglob("*"):
            if f.is_file() and f.name in names and "cities" not in f.relative_to(d / "surfaces").parts:
                files.append(f)
    for rel in ("ml/ml_summary.json", *(f"history/{n}" for n in HISTORY_FILES)):
        if (d / rel).exists():
            files.append(d / rel)
    return files


def pack(out: Path, cities: list[str]) -> int:
    files: list[Path] = []
    for cid in cities:
        cf = _city_files(cid)
        print(f"{CITIES[cid].name}: {len(cf)} files, {sum(f.stat().st_size for f in cf) / 1e6:.1f} MB")
        files += cf
    extra = DATA_ROOT / "rag" / "retrieval_eval.json"
    if extra.exists():
        files.append(extra)
    meta = {"created_at": datetime.now(timezone.utc).isoformat(), "cities": cities,
            "files": {str(f.relative_to(DATA_ROOT)).replace("\\", "/"): f.stat().st_size for f in files}}
    with tarfile.open(out, "w:gz", compresslevel=6) as tar:
        for f in files:
            tar.add(f, arcname=str(f.relative_to(DATA_ROOT)).replace("\\", "/"))
        tmp = Path(tempfile.mkstemp(suffix=".json")[1])
        tmp.write_text(json.dumps(meta, indent=1), encoding="utf-8")
        tar.add(tmp, arcname="bundle.json")
        tmp.unlink()
    h = hashlib.sha256(out.read_bytes()).hexdigest()
    print(f"-> {out} ({out.stat().st_size / 1e6:.1f} MB), sha256 {h}")
    print("Upload it (Azure Blob / GitHub Release) and set DATA_BUNDLE_URL on the server.")
    return 0


def _safe_members(tar: tarfile.TarFile):
    for m in tar.getmembers():
        p = Path(m.name)
        if p.is_absolute() or ".." in p.parts or not (m.isfile() or m.isdir()):
            raise SystemExit(f"refusing unsafe path in bundle: {m.name}")
        yield m


def fetch(urls: list[str], force: bool = False) -> int:
    import requests

    if not urls:
        print("No DATA_BUNDLE_URL set - using the data folder as it is.")
        return 0
    if MARKER.exists() and not force:
        done = json.loads(MARKER.read_text(encoding="utf-8"))
        if done.get("url") in urls:
            print(f"Data bundle already present ({done.get('created_at')}).")
            return 0
    last = None
    for url in urls:
        try:
            t = time.time()
            print(f"Downloading data bundle from {url.split('?')[0]} ...")
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "bundle.tar.gz"
                with requests.get(url, stream=True, timeout=(15, 300)) as r:
                    r.raise_for_status()
                    with path.open("wb") as f:
                        for chunk in r.iter_content(1 << 20):
                            f.write(chunk)
                with tarfile.open(path, "r:gz") as tar:
                    members = list(_safe_members(tar))
                    try:
                        tar.extractall(DATA_ROOT, members=members, filter="data")
                    except TypeError:      # Python < 3.12: paths are already checked above
                        tar.extractall(DATA_ROOT, members=members)
            meta = json.loads((DATA_ROOT / "bundle.json").read_text(encoding="utf-8"))
            MARKER.write_text(json.dumps({"url": url, "created_at": meta.get("created_at"),
                                          "cities": meta.get("cities")}), encoding="utf-8")
            print(f"Data bundle ready: {len(meta.get('files', {}))} files in {time.time() - t:.0f} s.")
            return 0
        except Exception as exc:     # try the next URL (e.g. Azure Blob gone -> GitHub Release)
            last = exc
            print(f"  failed: {exc}")
    print(f"No data bundle could be fetched ({last}); starting with the data folder as it is.")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pack")
    p.add_argument("--out", type=Path, default=Path("geosense-data.tar.gz"))
    p.add_argument("--city", action="append", choices=sorted(CITIES))
    f = sub.add_parser("fetch")
    f.add_argument("--url", action="append")
    f.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if a.cmd == "pack":
        cities = a.city or [c for c in CITIES if (CITIES[c].data_dir / "surfaces" / "manifest.json").exists()]
        return pack(a.out, cities)
    urls = a.url or [u.strip() for u in os.getenv("DATA_BUNDLE_URL", "").split(",") if u.strip()]
    return fetch(urls, a.force)


if __name__ == "__main__":
    raise SystemExit(main())
