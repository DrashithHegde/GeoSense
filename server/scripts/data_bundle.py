"""Pack, validate, publish, rollback, and fetch the GeoSense data bundle.

Supports two durable retrieval/publishing modes:
  1. Private Azure Blob Storage via Managed Identity (AZURE_STORAGE_ACCOUNT_URL + AZURE_STORAGE_CONTAINER)
     - Publishes immutable versioned archives: bundles/geosense-data-<YYYYMMDDTHHMMSSZ>.tar.gz
     - Tracks bundles/latest.json and bundles/previous.json for zero-downtime rollback
     - Also updates geosense-data.tar.gz for backward-compatible DATA_BUNDLE_URL SAS fetchers
  2. HTTPS URLs via DATA_BUNDLE_URL (fallback / Render / GitHub Release)
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT))

from app.core.cities import CITIES, DATA_ROOT  # noqa: E402
from app.services.surfaces.housekeeping import referenced_files  # noqa: E402

MARKER = DATA_ROOT / ".bundle.json"
HISTORY_FILES = ("history_summary.json", "change_if.json", "seasons.json")
LATEST_POINTER_BLOB = "bundles/latest.json"
PREVIOUS_POINTER_BLOB = "bundles/previous.json"
CANONICAL_BLOB = "geosense-data.tar.gz"


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


def validate_archive(archive: Path) -> dict[str, Any]:
    """Validate tar.gz integrity, safe paths, bundle.json, and every city's manifest.json."""
    if not archive.exists() or archive.stat().st_size == 0:
        raise ValueError(f"Archive missing or empty: {archive}")
    with tarfile.open(archive, "r:gz") as tar:
        members = list(_safe_members(tar))
        names = {m.name for m in members if m.isfile()}
        if "bundle.json" not in names:
            raise ValueError("Archive missing bundle.json")
        meta = json.loads(tar.extractfile("bundle.json").read().decode("utf-8"))
        for cid in meta.get("cities") or []:
            candidates = [f"cities/{cid}/surfaces/manifest.json", f"{cid}/surfaces/manifest.json"]
            if cid == "mumbai":
                candidates.insert(0, "surfaces/manifest.json")
            mpath = next((c for c in candidates if c in names), None)
            if not mpath:
                raise ValueError(f"Archive missing {candidates[0]} for city {cid}")
            mdata = json.loads(tar.extractfile(mpath).read().decode("utf-8"))
            if not isinstance(mdata.get("surfaces"), dict):
                raise ValueError(f"Invalid manifest structure in {mpath}")
    return meta


def pack(out: Path, cities: list[str]) -> int:
    files: list[Path] = []
    for cid in cities:
        cf = _city_files(cid)
        print(f"{CITIES[cid].name}: {len(cf)} files, {sum(f.stat().st_size for f in cf) / 1e6:.1f} MB")
        files += cf
    extra = DATA_ROOT / "rag" / "retrieval_eval.json"
    if extra.exists():
        files.append(extra)
    meta = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "cities": cities,
        "files": {str(f.relative_to(DATA_ROOT)).replace("\\", "/"): f.stat().st_size for f in files},
    }
    meta_bytes = json.dumps(meta, indent=1).encode("utf-8")
    with tarfile.open(out, "w:gz", compresslevel=6) as tar:
        for f in files:
            tar.add(f, arcname=str(f.relative_to(DATA_ROOT)).replace("\\", "/"))
        ti = tarfile.TarInfo(name="bundle.json")
        ti.size = len(meta_bytes)
        ti.mtime = int(time.time())
        tar.addfile(ti, io.BytesIO(meta_bytes))
    validate_archive(out)
    h = hashlib.sha256(out.read_bytes()).hexdigest()
    print(f"-> {out} ({out.stat().st_size / 1e6:.1f} MB), sha256 {h}")
    return 0


def _blob_service():
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient

    conn = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "").strip()
    account_url = os.getenv("AZURE_STORAGE_ACCOUNT_URL", "").strip()
    if conn:
        return BlobServiceClient.from_connection_string(conn)
    if account_url:
        in_azure = bool(os.getenv("IDENTITY_ENDPOINT") or os.getenv("MSI_ENDPOINT"))
        cred = DefaultAzureCredential(exclude_managed_identity_credential=not in_azure)
        return BlobServiceClient(account_url=account_url, credential=cred)
    return None


def publish_to_blob(archive: Path, *, container: str | None = None) -> dict[str, Any]:
    """Validate `archive`, upload versioned blob + update latest/previous pointers in private Blob Storage."""
    meta = validate_archive(archive)
    container = container or os.getenv("AZURE_STORAGE_CONTAINER", "geosense")
    service = _blob_service()
    if service is None:
        raise RuntimeError("Set AZURE_STORAGE_ACCOUNT_URL or AZURE_STORAGE_CONNECTION_STRING to publish to Blob")

    cc = service.get_container_client(container)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    versioned_blob = f"bundles/geosense-data-{stamp}.tar.gz"
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()

    # Read current latest pointer before overwriting so we preserve rollback target
    prev_pointer = None
    try:
        prev_bytes = cc.get_blob_client(LATEST_POINTER_BLOB).download_blob().readall()
        prev_pointer = json.loads(prev_bytes.decode("utf-8"))
    except Exception:
        pass

    with archive.open("rb") as stream:
        cc.get_blob_client(versioned_blob).upload_blob(stream, overwrite=True)

    # Verify uploaded blob size matches
    props = cc.get_blob_client(versioned_blob).get_blob_properties()
    if props.size != archive.stat().st_size:
        raise RuntimeError(f"Uploaded size mismatch: {props.size} != {archive.stat().st_size}")

    if prev_pointer:
        cc.get_blob_client(PREVIOUS_POINTER_BLOB).upload_blob(
            json.dumps(prev_pointer, indent=2).encode("utf-8"), overwrite=True
        )

    latest_pointer = {
        "blob": versioned_blob,
        "sha256": digest,
        "size_bytes": archive.stat().st_size,
        "created_at": meta.get("created_at"),
        "published_at": datetime.now(timezone.utc).isoformat(),
        "cities": meta.get("cities"),
        "previous_blob": prev_pointer.get("blob") if prev_pointer else None,
    }
    cc.get_blob_client(LATEST_POINTER_BLOB).upload_blob(
        json.dumps(latest_pointer, indent=2).encode("utf-8"), overwrite=True
    )
    # Keep canonical geosense-data.tar.gz in sync for SAS URL consumers
    with archive.open("rb") as stream:
        cc.get_blob_client(CANONICAL_BLOB).upload_blob(stream, overwrite=True)

    print(f"Published versioned bundle: {versioned_blob} ({props.size / 1e6:.1f} MB, sha256={digest[:12]}...)")
    return latest_pointer


def rollback_blob(*, container: str | None = None, target_blob: str | None = None) -> dict[str, Any]:
    """Restore bundles/latest.json and geosense-data.tar.gz to the previous valid bundle."""
    container = container or os.getenv("AZURE_STORAGE_CONTAINER", "geosense")
    service = _blob_service()
    if service is None:
        raise RuntimeError("Set AZURE_STORAGE_ACCOUNT_URL or AZURE_STORAGE_CONNECTION_STRING")
    cc = service.get_container_client(container)

    if target_blob:
        restore_meta = {"blob": target_blob, "rolled_back_at": datetime.now(timezone.utc).isoformat()}
    else:
        prev_bytes = cc.get_blob_client(PREVIOUS_POINTER_BLOB).download_blob().readall()
        restore_meta = json.loads(prev_bytes.decode("utf-8"))
        restore_meta["rolled_back_at"] = datetime.now(timezone.utc).isoformat()

    blob_name = restore_meta["blob"]
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / "rollback.tar.gz"
        with tmp_path.open("wb") as f:
            cc.get_blob_client(blob_name).download_blob().readinto(f)
        validate_archive(tmp_path)
        cc.get_blob_client(LATEST_POINTER_BLOB).upload_blob(
            json.dumps(restore_meta, indent=2).encode("utf-8"), overwrite=True
        )
        with tmp_path.open("rb") as f:
            cc.get_blob_client(CANONICAL_BLOB).upload_blob(f, overwrite=True)

    print(f"Rolled back latest bundle to: {blob_name}")
    return restore_meta


def _safe_members(tar: tarfile.TarFile):
    for m in tar.getmembers():
        p = Path(m.name)
        if p.is_absolute() or ".." in p.parts or not (m.isfile() or m.isdir()):
            raise SystemExit(f"refusing unsafe path in bundle: {m.name}")
        yield m


def _extract_validated(path: Path, source_label: str, extra_marker: dict[str, Any] | None = None) -> dict[str, Any]:
    meta = validate_archive(path)
    with tarfile.open(path, "r:gz") as tar:
        members = list(_safe_members(tar))
        try:
            tar.extractall(DATA_ROOT, members=members, filter="data")
        except TypeError:
            tar.extractall(DATA_ROOT, members=members)
    marker = {
        "source": source_label,
        "created_at": meta.get("created_at"),
        "cities": meta.get("cities"),
        **(extra_marker or {}),
    }
    MARKER.write_text(json.dumps(marker, indent=2), encoding="utf-8")
    return meta


def _fetch_from_blob(force: bool) -> bool:
    service = _blob_service()
    if service is None:
        return False
    container = os.getenv("AZURE_STORAGE_CONTAINER", "geosense")
    cc = service.get_container_client(container)
    blob_name = CANONICAL_BLOB
    pointer: dict[str, Any] = {}
    try:
        pointer = json.loads(cc.get_blob_client(LATEST_POINTER_BLOB).download_blob().readall().decode("utf-8"))
        blob_name = pointer.get("blob") or CANONICAL_BLOB
    except Exception:
        pass

    if MARKER.exists() and not force:
        try:
            done = json.loads(MARKER.read_text(encoding="utf-8"))
            if pointer.get("sha256") and done.get("sha256") == pointer["sha256"]:
                print(f"Data bundle already up-to-date ({blob_name}).")
                return True
        except Exception:
            pass

    t = time.time()
    print(f"Downloading data bundle from Azure Blob ({container}/{blob_name}) via Managed Identity...")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "bundle.tar.gz"
        with path.open("wb") as f:
            cc.get_blob_client(blob_name).download_blob().readinto(f)
        if pointer.get("sha256"):
            got = hashlib.sha256(path.read_bytes()).hexdigest()
            if got != pointer["sha256"]:
                raise ValueError(f"Blob sha256 mismatch: {got} != {pointer['sha256']}")
        meta = _extract_validated(
            path,
            f"blob://{container}/{blob_name}",
            {"blob": blob_name, "sha256": pointer.get("sha256")},
        )
    print(f"Data bundle ready from Blob: {len(meta.get('files', {}))} files in {time.time() - t:.0f} s.")
    return True


def fetch(urls: list[str], force: bool = False) -> int:
    import requests

    # 1. Prefer private Azure Blob Storage via Managed Identity when configured
    if os.getenv("AZURE_STORAGE_ACCOUNT_URL", "").strip() or os.getenv("AZURE_STORAGE_CONNECTION_STRING", "").strip():
        try:
            if _fetch_from_blob(force):
                return 0
        except Exception as exc:
            print(f"  Azure Blob fetch failed ({exc}); falling back to DATA_BUNDLE_URL...")

    if not urls:
        print("No DATA_BUNDLE_URL set - using the data folder as it is.")
        return 0
    if MARKER.exists() and not force:
        done = json.loads(MARKER.read_text(encoding="utf-8"))
        if done.get("url") in urls or done.get("source") in urls:
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
                meta = _extract_validated(path, url, {"url": url})
            print(f"Data bundle ready: {len(meta.get('files', {}))} files in {time.time() - t:.0f} s.")
            return 0
        except Exception as exc:
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

    pub = sub.add_parser("publish")
    pub.add_argument("--out", type=Path, default=Path("geosense-data.tar.gz"))
    pub.add_argument("--city", action="append", choices=sorted(CITIES))

    rb = sub.add_parser("rollback")
    rb.add_argument("--blob", default=None)

    f = sub.add_parser("fetch")
    f.add_argument("--url", action="append")
    f.add_argument("--force", action="store_true")

    a = ap.parse_args()
    if a.cmd == "pack":
        cities = a.city or [c for c in CITIES if (CITIES[c].data_dir / "surfaces" / "manifest.json").exists()]
        return pack(a.out, cities)
    if a.cmd == "publish":
        cities = a.city or [c for c in CITIES if (CITIES[c].data_dir / "surfaces" / "manifest.json").exists()]
        rc = pack(a.out, cities)
        if rc:
            return rc
        publish_to_blob(a.out)
        return 0
    if a.cmd == "rollback":
        rollback_blob(target_blob=a.blob)
        return 0
    urls = a.url or [u.strip() for u in os.getenv("DATA_BUNDLE_URL", "").split(",") if u.strip()]
    return fetch(urls, a.force)


if __name__ == "__main__":
    raise SystemExit(main())
