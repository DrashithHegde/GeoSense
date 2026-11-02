"""Zonal statistics from the real scientific GeoTIFFs into the 300 m spatial cells.

PIXEL (GeoTIFF)  ->  CELL (spatial_cells, 300 m)  ->  feature vector for ML

Each raster is labelled with cell ids via rasterisation on its own native grid
(no resampling of science values), then aggregated with np.bincount. Nothing
is imputed: a statistic is NULL when a cell has too few valid pixels.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.features import rasterize
from shapely import wkb
from sqlalchemy import text

SERVER_ROOT = Path(__file__).resolve().parents[3]
SURFACE_ROOT = SERVER_ROOT / "data" / "surfaces"
MANIFEST = SURFACE_ROOT / "manifest.json"
ML_DIR = SERVER_ROOT / "data" / "ml"

from app.services.qc import LST_QC_MIN_C  # noqa: E402
MIN_VALID_FRACTION = 0.30      # a cell statistic needs >=30% valid pixels
MIN_WATER_PIXELS = 30          # >= 3,000 m² of detected water for a WH cell mean
FEATURE_VERSION = "cell_features_v1"


@dataclass
class Cell:
    id: int
    code: str
    municipality: str | None
    geom: Any
    lon: float
    lat: float


def load_cells(db) -> list[Cell]:
    rows = db.execute(text(
        "SELECT id, cell_code, municipality_name, ST_AsBinary(geometry) AS g, "
        "ST_X(centroid) AS lon, ST_Y(centroid) AS lat FROM spatial_cells ORDER BY id"
    )).mappings().all()
    return [Cell(r["id"], r["cell_code"], r["municipality_name"], wkb.loads(bytes(r["g"])), r["lon"], r["lat"]) for r in rows]


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["surfaces"]


def _tif(rec: dict, folder: str) -> Path | None:
    if not rec or rec.get("generation_status") in ("insufficient_coverage", "not_generated"):
        return None
    if rec.get("geotiff_filename"):
        p = SURFACE_ROOT / rec["geotiff_filename"]
    elif rec.get("files", {}).get("geotiff"):
        p = SURFACE_ROOT / folder / rec["files"]["geotiff"]
    else:
        return None
    return p if p.exists() else None


def _labels(cells: list[Cell], ds) -> np.ndarray:
    return rasterize(((c.geom, c.id) for c in cells), out_shape=(ds.height, ds.width), transform=ds.transform,
                     fill=0, dtype="int32", all_touched=False)


def _stats(labels: np.ndarray, values: np.ndarray, valid: np.ndarray, n: int) -> dict[str, np.ndarray]:
    lab = labels.ravel()
    v = values.ravel().astype("float64")
    m = valid.ravel()
    total = np.bincount(lab, minlength=n)
    cnt = np.bincount(lab[m], minlength=n)
    s = np.bincount(lab[m], weights=v[m], minlength=n)
    ss = np.bincount(lab[m], weights=v[m] ** 2, minlength=n)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = s / cnt
        std = np.sqrt(np.maximum(ss / cnt - mean ** 2, 0))
    return {"total": total, "count": cnt, "mean": mean, "std": std}


def _frac(labels, cond, valid, n):
    lab = labels.ravel()
    m = valid.ravel()
    c = np.bincount(lab[m & cond.ravel()], minlength=n)
    t = np.bincount(lab[m], minlength=n)
    with np.errstate(invalid="ignore", divide="ignore"):
        return c / t


def _read(path: Path):
    ds = rasterio.open(path)
    arr = ds.read(1).astype("float32")
    valid = np.isfinite(arr)
    if ds.nodata is not None:
        valid &= arr != ds.nodata
    return ds, arr, valid


def compute_cell_features(cells: list[Cell]) -> tuple[list[dict], dict]:
    S = _manifest()
    n = max(c.id for c in cells) + 1
    idx = np.array([c.id for c in cells])
    feats: dict[str, np.ndarray] = {}
    sources: dict[str, Any] = {}

    # ── NDVI (Sentinel-2, 10 m) ──
    p = _tif(S.get("ndvi"), "ndvi")
    if p:
        ds, a, v = _read(p)
        lab = _labels(cells, ds)
        st = _stats(lab, a, v, n)
        ok = st["count"] >= MIN_VALID_FRACTION * np.maximum(st["total"], 1)
        land = v & (a >= 0)
        feats["ndvi_mean"] = np.where(ok, st["mean"], np.nan)
        feats["ndvi_std"] = np.where(ok, st["std"], np.nan)
        feats["veg_frac"] = np.where(ok, _frac(lab, a >= 0.5, v, n), np.nan)
        feats["built_frac"] = np.where(ok, _frac(lab, (a >= 0) & (a < 0.2), v, n), np.nan)
        feats["openwater_frac"] = np.where(ok, _frac(lab, a < 0, v, n), np.nan)
        # distance (m) to nearest open water (NDVI < 0: sea, creeks, lakes) — coastal/lake cooling proxy
        from scipy.ndimage import distance_transform_edt
        px_m = abs(ds.transform.a) * 111320.0 * np.cos(np.radians(19.1))
        dist = distance_transform_edt(~(v & (a < 0))).astype("float32") * px_m
        dst = _stats(lab, dist, v, n)
        feats["dist_water_m"] = np.where(ok, dst["mean"], np.nan)
        del dist
        land_st = _stats(lab, a, land, n)
        feats["ndvi_land_mean"] = np.where(land_st["count"] > 0, land_st["mean"], np.nan)
        sources["ndvi"] = {"file": p.name, "period": S["ndvi"].get("source_period"), "scale_m": 10,
                           "dataset": S["ndvi"].get("dataset")}
        ds.close()

    # ── Water Health (Sentinel-2, 10 m; water pixels only) ──
    p = _tif(S.get("water_health"), "water-health")
    if p:
        ds, a, v = _read(p)
        lab = _labels(cells, ds)
        st = _stats(lab, a, v, n)
        feats["water_px"] = st["count"].astype("float64")
        feats["water_frac"] = np.where(st["total"] > 0, st["count"] / np.maximum(st["total"], 1), np.nan)
        feats["wh_mean"] = np.where(st["count"] >= MIN_WATER_PIXELS, st["mean"], np.nan)
        feats["wh_std"] = np.where(st["count"] >= MIN_WATER_PIXELS, st["std"], np.nan)
        sources["water_health"] = {"file": p.name, "period": S["water_health"].get("source_period"), "scale_m": 10}
        ds.close()

    # ── LST (Landsat 8/9 C2 L2, 30 m) ──
    p = _tif(S.get("lst"), "lst")
    if p:
        ds, a, v = _read(p)
        v &= a >= LST_QC_MIN_C
        lab = _labels(cells, ds)
        st = _stats(lab, a, v, n)
        ok = st["count"] >= MIN_VALID_FRACTION * np.maximum(st["total"], 1)
        feats["lst_mean"] = np.where(ok, st["mean"], np.nan)
        feats["lst_std"] = np.where(ok, st["std"], np.nan)
        feats["lst_valid_frac"] = np.where(st["total"] > 0, st["count"] / np.maximum(st["total"], 1), np.nan)
        sources["lst"] = {"file": p.name, "period": S["lst"].get("source_period"), "scale_m": 30,
                          "qc_min_c": LST_QC_MIN_C}
        ds.close()

    # ── AQI (OpenAQ CPCB IDW) — only if a real station surface exists ──
    p = _tif(S.get("aqi"), "aqi")
    if p and S["aqi"].get("generation_status") == "generated":
        ds, a, v = _read(p)
        lab = _labels(cells, ds)
        # coarse grid: centroid fallback where a cell has no pixel centre inside it
        st = _stats(lab, a, v, n)
        feats["aqi_idw"] = np.where(st["count"] > 0, st["mean"], np.nan)
        sources["aqi"] = {"file": p.name, "source_timestamp": S["aqi"].get("source_timestamp"),
                          "method": S["aqi"].get("methodology")}
        ds.close()

    rows = []
    for c in cells:
        r = {"cell_id": c.id, "cell_code": c.code, "municipality": c.municipality, "lon": c.lon, "lat": c.lat}
        for k, arr in feats.items():
            val = arr[c.id]
            r[k] = None if not np.isfinite(val) else float(val)
        rows.append(r)
    return rows, sources


def snapshot_timestamp(sources: dict) -> datetime:
    """Analytical snapshot = latest LST/NDVI composite timestamp in the manifest."""
    S = _manifest()
    stamps = []
    for k in ("ndvi", "lst"):
        ts = (S.get(k) or {}).get("timestamp")
        if ts:
            stamps.append(datetime.strptime(ts, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc))
    return max(stamps) if stamps else datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def persist_cell_features(db, rows: list[dict], sources: dict, observed_at: datetime) -> int:
    meta = {"cell_features": {"version": FEATURE_VERSION, "sources": sources,
                              "computed_at": datetime.now(timezone.utc).isoformat()}}
    payload = []
    for r in rows:
        payload.append({
            "cell_id": r["cell_id"], "obs": observed_at,
            "ndvi": r.get("ndvi_mean"), "lst": r.get("lst_mean"), "wh": r.get("wh_mean"),
            "wext": None if r.get("water_px") is None else r["water_px"] * 100.0,
            "aqi": None if r.get("aqi_idw") is None else int(round(r["aqi_idw"])),
            "src": "openaq_cpcb_idw" if r.get("aqi_idw") is not None else None,
            "meta": json.dumps(meta),
            "fv": json.dumps({"schema_version": "2.0", "feature_version": FEATURE_VERSION, "raw_values": r,
                              "sources": sources, "snapshot_at": observed_at.isoformat()}),
        })
    db.execute(text("""
        INSERT INTO environment_data (cell_id, observed_at, ndvi, lst, water_health_score, water_extent_m2,
                                      aqi, aqi_source_type, source_metadata)
        VALUES (:cell_id, :obs, :ndvi, :lst, :wh, :wext, :aqi, :src, CAST(:meta AS jsonb))
        ON CONFLICT (cell_id, observed_at) DO UPDATE SET
            ndvi = EXCLUDED.ndvi, lst = EXCLUDED.lst, water_health_score = EXCLUDED.water_health_score,
            water_extent_m2 = EXCLUDED.water_extent_m2, aqi = EXCLUDED.aqi,
            aqi_source_type = EXCLUDED.aqi_source_type,
            source_metadata = environment_data.source_metadata || EXCLUDED.source_metadata
    """), payload)
    db.execute(text("""
        INSERT INTO engineered_features (cell_id, observed_at, feature_values, environment_data_id)
        SELECT :cell_id, :obs, CAST(:fv AS jsonb),
               (SELECT id FROM environment_data WHERE cell_id = :cell_id AND observed_at = :obs)
        ON CONFLICT (cell_id, observed_at) DO UPDATE SET
            feature_values = EXCLUDED.feature_values, environment_data_id = EXCLUDED.environment_data_id
    """), payload)
    return len(payload)


def export_csv(rows: list[dict], observed_at: datetime) -> Path:
    import csv
    ML_DIR.mkdir(parents=True, exist_ok=True)
    path = ML_DIR / f"cell_features_{observed_at.strftime('%Y%m%dT%H%M%SZ')}.csv"
    keys = sorted({k for r in rows for k in r})
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    return path
