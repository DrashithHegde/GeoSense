"""Supporting Sentinel-2 indices: NDMI (vegetation moisture) and NDBI (built-up intensity).

These are NOT map layers. They sit inside the existing Vegetation and LST layers to
explain them ("green but dry", "highly built-up"), exactly as the project spec asks.

Both use band B11 (SWIR-1), whose native resolution is 20 m, so they are exported at
20 m — never relabelled as 10 m. The composite window, cloud mask (QA60) and median
compositing are the same as the NDVI surface, so the three indices are comparable.

    NDMI = (B8 - B11) / (B8 + B11)   Gao (1996) — vegetation liquid-water content
    NDBI = (B11 - B8) / (B11 + B8)   Zha, Gao & Ni (2003) — built-up / bare intensity

Note NDBI = -NDMI exactly (same two bands, swapped). So only ONE raster (NDMI) is exported;
NDBI is derived as -1 x NDMI when read, and documented as such. They are read in two
contexts (moisture of vegetated pixels vs built-up intensity of land), but never used as
two independent model features or both counted in the composite: that would double-count
a single measurement.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import rasterio

SERVER_ROOT = Path(__file__).resolve().parents[3]
SURFACE_ROOT = SERVER_ROOT / "data" / "surfaces"
MANIFEST_PATH = SURFACE_ROOT / "manifest.json"
CRS = "EPSG:4326"
NODATA_VALUE = -9999.0
SCALE_METERS = 20  # B11 native resolution

INDEX_SPECS: dict[str, dict[str, Any]] = {
    "ndmi": {
        "bands": ("B8", "B11"),
        "formula": "normalizedDifference(B8, B11) = (B8 - B11) / (B8 + B11)",
        "semantic_label": "NDMI · Vegetation moisture",
        "parent_layer": "ndvi",
        "interpretation": "Vegetation liquid-water signal. Higher = moister canopy; low NDMI with high NDVI "
                          "suggests green but water-stressed vegetation. Meaningful mainly on vegetated pixels.",
        "citation": "Gao, B.-C. (1996). NDWI — A normalized difference water index for remote sensing of "
                    "vegetation liquid water from space. Remote Sensing of Environment 58(3), 257-266.",
    },
    "ndbi": {
        "derived_from": "ndmi",
        "value_transform": "negate",
        "bands": ("B11", "B8"),
        "formula": "normalizedDifference(B11, B8) = (B11 - B8) / (B11 + B8) = -NDMI",
        "semantic_label": "NDBI · Built-up intensity",
        "parent_layer": "lst",
        "interpretation": "Built-up / bare-surface signal. Higher = more built-up or bare surface. Context for "
                          "surface heat, not a temperature; bare soil and some dry vegetation also raise it.",
        "citation": "Zha, Y., Gao, J. & Ni, S. (2003). Use of normalized difference built-up index in "
                    "automatically mapping urban areas from TM imagery. Int. J. Remote Sensing 24(3), 583-594.",
    },
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def write_manifest_record(metric: str, record: dict[str, Any], manifest_path: Path = MANIFEST_PATH) -> None:
    current: dict[str, Any] = {"version": 1, "surfaces": {}}
    if manifest_path.exists():
        current = json.loads(manifest_path.read_text(encoding="utf-8"))
    current.setdefault("surfaces", {})[metric] = record
    tmp = manifest_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(manifest_path)


def ndvi_window(manifest_path: Path = MANIFEST_PATH) -> tuple[str, str] | None:
    """Same composite window as the published NDVI surface, so indices stay comparable."""
    try:
        rec = json.loads(manifest_path.read_text(encoding="utf-8"))["surfaces"]["ndvi"]
        p = rec.get("source_period") or {}
        return (p["start"], p["end"]) if p.get("start") and p.get("end") else None
    except Exception:
        return None


# ── Earth Engine (runs on the user's machine) ────────────────────────────────

def build_index_composite(index: str, *, start_date: str, end_date: str, bounds):
    import ee
    from gee.ingest_ndvi_ndwi import S2_DATASET, mask_s2_sr

    spec = INDEX_SPECS[index]
    region = ee.Geometry.Rectangle(list(bounds), proj=CRS, geodesic=False)
    b1, b2 = spec["bands"]
    collection = (
        ee.ImageCollection(S2_DATASET)
        .filterDate(start_date, end_date)
        .filterBounds(region)
        .select(["B8", "B11", "QA60"])
        .map(mask_s2_sr)
        .map(lambda img: img.normalizedDifference([b1, b2]).rename(index.upper()))
    )
    count = int(collection.size().getInfo())
    if count == 0:
        raise ValueError(f"No Sentinel-2 images for {index} in {start_date}..{end_date}")
    return collection.median().clip(region), region, count


def _extract_tiff(path: Path) -> Path:
    if not zipfile.is_zipfile(path):
        return path
    with zipfile.ZipFile(path) as z:
        tifs = [m for m in z.namelist() if m.lower().endswith((".tif", ".tiff"))]
        if len(tifs) != 1:
            raise ValueError("Earth Engine download did not contain exactly one GeoTIFF")
        out = path.parent / Path(tifs[0]).name
        with z.open(tifs[0]) as s, out.open("wb") as t:
            shutil.copyfileobj(s, t)
    path.unlink()
    return out


def download_geotiff(image, region, destination: Path, scale: int = SCALE_METERS) -> None:
    """Download in two tiles (keeps each request under the EE size limit) and mosaic."""
    import time

    import ee
    import requests
    from rasterio.merge import merge

    coords = region.coordinates().getInfo()[0]
    xs, ys = [c[0] for c in coords], [c[1] for c in coords]
    west, east, south, north = min(xs), max(xs), min(ys), max(ys)
    mid = (west + east) / 2
    tiles = [ee.Geometry.Rectangle([west, south, mid, north], proj=CRS, geodesic=False),
             ee.Geometry.Rectangle([mid, south, east, north], proj=CRS, geodesic=False)]
    with tempfile.TemporaryDirectory(prefix="idx_tiles_") as tmp:
        paths = []
        for i, t in enumerate(tiles):
            url = image.unmask(NODATA_VALUE).getDownloadURL(
                {"scale": scale, "crs": CRS, "region": t, "format": "GEO_TIFF", "filePerBand": False})
            dest = Path(tmp) / f"t{i}.raw"
            for attempt in range(5):
                try:
                    r = requests.get(url, timeout=240)
                    r.raise_for_status()
                    dest.write_bytes(r.content)
                    break
                except requests.HTTPError as exc:
                    code = exc.response.status_code if exc.response is not None else 0
                    if code >= 500 and attempt < 4:
                        time.sleep(2 ** attempt + attempt)
                        continue
                    raise
            paths.append(_extract_tiff(dest))
        dss = [rasterio.open(p) for p in paths]
        try:
            arr, transform = merge(dss, nodata=NODATA_VALUE)
            meta = dss[0].meta.copy()
            meta.update(height=arr.shape[1], width=arr.shape[2], count=1, transform=transform, crs=CRS,
                        nodata=NODATA_VALUE, dtype="float32", compress="deflate")
            with rasterio.open(destination, "w", **meta) as out:
                out.write(arr[:1].astype("float32"))
        finally:
            for d in dss:
                d.close()


# ── publish (pure; testable without Earth Engine) ────────────────────────────

def publish_index_geotiff(index: str, source_path: Path, *, start_date: str, end_date: str, image_count: int,
                          output_root: Path = SURFACE_ROOT) -> dict[str, Any]:
    """Validate a real export, store the scientific GeoTIFF unchanged, record provenance."""
    spec = INDEX_SPECS[index]
    with rasterio.open(source_path) as src:
        if src.count != 1:
            raise ValueError(f"{index} export must contain exactly one band")
        arr = src.read(1).astype("float32")
        nd = src.nodata if src.nodata is not None else NODATA_VALUE
        valid = np.isfinite(arr) & (arr != nd) & (arr >= -1.0001) & (arr <= 1.0001)
        if not valid.any():
            raise ValueError(f"{index} export has no valid pixels")
        meta = src.meta.copy()
    arr = np.where(valid, arr, NODATA_VALUE).astype("float32")
    ts = datetime.fromisoformat(end_date).strftime("%Y%m%dT000000Z")
    folder = output_root / "indices"
    folder.mkdir(parents=True, exist_ok=True)
    tif = folder / f"{index}_{ts}.tif"
    meta.update(dtype="float32", nodata=NODATA_VALUE, count=1, compress="deflate")
    with rasterio.open(tif, "w", **meta) as out:
        out.write(arr, 1)
    v = arr[valid]
    record = {
        "metric": index,
        "role": "supporting_index",
        "map_layer": False,
        "parent_layer": spec["parent_layer"],
        "semantic_label": spec["semantic_label"],
        "generation_status": "generated",
        "dataset": "COPERNICUS/S2_SR_HARMONIZED",
        "source": "Google Earth Engine / Sentinel-2",
        "methodology": f"Sentinel-2 median composite {index.upper()}",
        "formula": spec["formula"],
        "interpretation": spec["interpretation"],
        "citation": spec["citation"],
        "cloud_mask": "QA60 cloud + cirrus bits (same as NDVI)",
        "scale_m": SCALE_METERS,
        "source_scale_m": SCALE_METERS,
        "resolution_note": "B11 (SWIR-1) is native 20 m; exported at 20 m, not resampled to 10 m",
        "source_period": {"start": start_date, "end": end_date},
        "image_count": int(image_count),
        "timestamp": ts,
        "geotiff_filename": f"indices/{tif.name}",
        "nodata_value": NODATA_VALUE,
        "valid_pixels": int(valid.sum()),
        "statistics": {"p02": float(np.percentile(v, 2)), "median": float(np.median(v)),
                       "p98": float(np.percentile(v, 98))},
        "checksums": {"geotiff_sha256": _sha256(tif)},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    write_manifest_record(index, record, output_root / "manifest.json")
    return record


def publish_derived_records(ndmi_record: dict[str, Any], output_root: Path = SURFACE_ROOT) -> dict[str, Any]:
    """Manifest record for NDBI pointing at the NDMI GeoTIFF with value_transform = negate."""
    spec = INDEX_SPECS["ndbi"]
    st = ndmi_record.get("statistics") or {}
    rec = {**{k: ndmi_record[k] for k in ("generation_status", "dataset", "source", "cloud_mask", "scale_m",
                                            "source_scale_m", "resolution_note", "source_period", "image_count",
                                            "timestamp", "geotiff_filename", "nodata_value", "valid_pixels",
                                            "checksums", "generated_at")},
           "metric": "ndbi", "role": "supporting_index", "map_layer": False, "parent_layer": spec["parent_layer"],
           "semantic_label": spec["semantic_label"], "methodology": "Derived: NDBI = -NDMI (same B8/B11 composite)",
           "derived_from": "ndmi", "value_transform": "negate", "formula": spec["formula"],
           "interpretation": spec["interpretation"], "citation": spec["citation"],
           "statistics": {"p02": -st.get("p98", 0.0), "median": -st.get("median", 0.0), "p98": -st.get("p02", 0.0)}}
    write_manifest_record("ndbi", rec, output_root / "manifest.json")
    return rec


def read_index_pixel(index: str, lon: float, lat: float, manifest_path: Path = MANIFEST_PATH) -> dict | None:
    """Exact 20 m pixel value (NDBI applies the documented -1 transform to the NDMI file)."""
    from rasterio.windows import Window
    try:
        rec = json.loads(manifest_path.read_text(encoding="utf-8"))["surfaces"].get(index) or {}
    except Exception:
        return None
    if rec.get("generation_status") != "generated" or not rec.get("geotiff_filename"):
        return None
    path = manifest_path.parent / rec["geotiff_filename"]
    if not path.exists():
        return None
    with rasterio.open(path) as ds:
        b = ds.bounds
        if not (b.left <= lon <= b.right and b.bottom <= lat <= b.top):
            return {"value": None, "nodata": True}
        r, c = ds.index(lon, lat)
        v = float(ds.read(1, window=Window(c, r, 1, 1))[0, 0])
        nd = (ds.nodata is not None and v == ds.nodata) or not np.isfinite(v)
    if not nd and rec.get("value_transform") == "negate":
        v = -v
    return {"value": None if nd else round(v, 3), "nodata": nd, "resolution_m": rec.get("scale_m"),
            "source_period": rec.get("source_period"), "derived_from": rec.get("derived_from")}


def generate_index_surface(index: str, *, start_date: str, end_date: str) -> dict[str, Any]:
    from app.services.municipality_boundaries import get_study_region_bounds
    from gee.gee_client import initialize_ee

    initialize_ee()
    image, region, count = build_index_composite(index, start_date=start_date, end_date=end_date,
                                                 bounds=get_study_region_bounds())
    with tempfile.TemporaryDirectory(prefix=f"geosense-{index}-") as tmp:
        dl = Path(tmp) / f"{index}.tif"
        download_geotiff(image, region, dl)
        rec = publish_index_geotiff(index, dl, start_date=start_date, end_date=end_date, image_count=count)
    if index == "ndmi":
        publish_derived_records(rec)
    return rec
