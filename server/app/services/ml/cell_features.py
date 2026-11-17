"""Zonal statistics from the real scientific GeoTIFFs into the 300 m spatial cells.

PIXEL (GeoTIFF)  ->  CELL (spatial_cells, 300 m)  ->  feature vector for ML

Each raster is labelled with cell ids via rasterisation on its own native grid
(no resampling of science values), then aggregated with np.bincount. Nothing
is imputed: a statistic is NULL when a cell has too few valid pixels.
"""
from __future__ import annotations
from app.core.cities import city_path

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
SURFACE_ROOT = city_path("surfaces")
MANIFEST = city_path("surfaces", "manifest.json")
ML_DIR = city_path("ml")

from app.services.qc import lst_qc_min_c  # noqa: E402
MIN_VALID_FRACTION = 0.30      # a cell statistic needs >=30% valid pixels
MIN_WATER_PIXELS = 30          # >= 3,000 m² of detected water for a WH cell mean
FEATURE_VERSION = "cell_features_v2"
NDMI_VEG_NDVI = 0.4            # a 20 m pixel counts as vegetated for NDMI when its mean NDVI >= 0.4
MIN_VEG_PIXELS_20M = 10        # >= 4,000 m² of vegetation before a cell gets a vegetation-moisture value


@dataclass
class Cell:
    id: int
    code: str
    municipality: str | None
    geom: Any
    lon: float
    lat: float


def load_cells(db) -> list[Cell]:
    """The 300 m cells of the city in use."""
    from app.core.cities import current_city_id
    rows = db.execute(text(
        "SELECT id, cell_code, municipality_name, ST_AsBinary(geometry) AS g, "
        "ST_X(centroid) AS lon, ST_Y(centroid) AS lat FROM spatial_cells WHERE city = :city ORDER BY id"
    ), {"city": current_city_id()}).mappings().all()
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
        mid_lat = (ds.bounds.bottom + ds.bounds.top) / 2.0      # metres per degree depend on latitude
        px_m = abs(ds.transform.a) * 111320.0 * np.cos(np.radians(mid_lat))
        dist = distance_transform_edt(~(v & (a < 0))).astype("float32") * px_m
        dst = _stats(lab, dist, v, n)
        feats["dist_water_m"] = np.where(ok, dst["mean"], np.nan)
        del dist
        land_st = _stats(lab, a, land, n)
        feats["ndvi_land_mean"] = np.where(land_st["count"] > 0, land_st["mean"], np.nan)
        sources["ndvi"] = {"file": p.name, "period": S["ndvi"].get("source_period"), "scale_m": 10,
                           "dataset": S["ndvi"].get("dataset")}
        ds.close()

    # ── NDMI (Sentinel-2, 20 m; NDBI = -NDMI is derived, never a second feature) ──
    p = _tif(S.get("ndmi"), "indices")
    pn = _tif(S.get("ndvi"), "ndvi")
    if p and pn:
        from rasterio.enums import Resampling
        from rasterio.vrt import WarpedVRT
        ds, a, v = _read(p)
        # NDVI averaged onto the 20 m NDMI grid, only to decide which 20 m pixels are vegetated / land
        with rasterio.open(pn) as src, WarpedVRT(src, crs=ds.crs, transform=ds.transform, width=ds.width,
                                                height=ds.height, resampling=Resampling.average,
                                                src_nodata=src.nodata, nodata=np.nan) as vrt:
            nd20 = vrt.read(1).astype("float32")
        lab = _labels(cells, ds)
        veg = v & np.isfinite(nd20) & (nd20 >= NDMI_VEG_NDVI)
        land = v & np.isfinite(nd20) & (nd20 >= 0)
        vs = _stats(lab, a, veg, n)
        ls = _stats(lab, a, land, n)
        feats["ndmi_veg_mean"] = np.where(vs["count"] >= MIN_VEG_PIXELS_20M, vs["mean"], np.nan)
        ok = ls["count"] >= MIN_VALID_FRACTION * np.maximum(ls["total"], 1)
        feats["ndbi_land_mean"] = np.where(ok, -ls["mean"], np.nan)
        sources["ndmi"] = {"file": p.name, "period": S["ndmi"].get("source_period"), "scale_m": 20,
                           "ndbi": "derived as -NDMI over land pixels"}
        ds.close()
        del nd20

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
        v &= a >= lst_qc_min_c()
        lab = _labels(cells, ds)
        st = _stats(lab, a, v, n)
        ok = st["count"] >= MIN_VALID_FRACTION * np.maximum(st["total"], 1)
        feats["lst_mean"] = np.where(ok, st["mean"], np.nan)
        feats["lst_std"] = np.where(ok, st["std"], np.nan)
        feats["lst_valid_frac"] = np.where(st["total"] > 0, st["count"] / np.maximum(st["total"], 1), np.nan)
        sources["lst"] = {"file": p.name, "period": S["lst"].get("source_period"), "scale_m": 30,
                          "qc_min_c": lst_qc_min_c()}
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

    # ── Composite v2 components (30 m) → per-cell component means + decomposable cell score ──
    rec = S.get("composite") or {}
    cp = SURFACE_ROOT / rec["components_filename"] if rec.get("components_filename") else None
    if cp and cp.exists():
        from app.services.composite_v2 import COMPONENTS
        ds = rasterio.open(cp)
        lab = _labels(cells, ds)
        for i, k in enumerate(COMPONENTS, start=1):
            a = ds.read(i).astype("float32")
            v = np.isfinite(a) & (a != ds.nodata)
            st = _stats(lab, a, v, n)
            ok = st["count"] >= MIN_VALID_FRACTION * np.maximum(st["total"], 1)
            feats[f"comp_{k}"] = np.where(ok, st["mean"], np.nan)
        sources["composite"] = {"file": cp.name, "weights": rec.get("weights"), "version": rec.get("version")}
        ds.close()

    rows = []
    for c in cells:
        r = {"cell_id": c.id, "cell_code": c.code, "municipality": c.municipality, "lon": c.lon, "lat": c.lat}
        for k, arr in feats.items():
            val = arr[c.id]
            r[k] = None if not np.isfinite(val) else float(val)
        if any(f"comp_{k}" in feats for k in ("heat", "surface", "air")):
            from app.services.composite_v2 import WEIGHTS, contributions
            b = contributions({k: r.get(f"comp_{k}") for k in ("heat", "surface", "air")},
                              (S.get("composite") or {}).get("weights") or WEIGHTS)
            r["composite_cell"] = b["score"] if b else None
            r["composite_coverage"] = int(b["coverage"][0]) if b else None
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


# ─────────────────────────────────────────────────────────────────────────────
# Live values for ONE cell, from the GeoTIFFs the map is showing right now
# ─────────────────────────────────────────────────────────────────────────────

def _cover_window(ds, w, s, e, n):
    """Integer window covering the bounds plus one pixel each side (so no pixel whose centre is
    inside the cell is cut off by rounding), clipped to the raster."""
    from rasterio.windows import Window, from_bounds as window_from_bounds
    f = window_from_bounds(w, s, e, n, transform=ds.transform)
    c0 = int(np.floor(f.col_off)) - 1
    r0 = int(np.floor(f.row_off)) - 1
    c1 = int(np.ceil(f.col_off + f.width)) + 1
    r1 = int(np.ceil(f.row_off + f.height)) + 1
    c0, r0 = max(c0, 0), max(r0, 0)
    c1, r1 = min(c1, ds.width), min(r1, ds.height)
    return Window(c0, r0, max(c1 - c0, 0), max(r1 - r0, 0))


def _cell_window_stats(path: Path, geom, valid_fn=None) -> tuple[float, int, int] | None:
    """Mean, valid count and total pixel count of `path` inside the cell polygon (same rules as
    compute_cell_features: pixel centres inside the cell, NoData excluded). Reads only a window."""
    w, s, e, n = geom.bounds
    with rasterio.open(path) as ds:
        win = _cover_window(ds, w, s, e, n)
        a = ds.read(1, window=win).astype("float32")
        tr = ds.window_transform(win)
        valid = np.isfinite(a)
        if ds.nodata is not None:
            valid &= a != ds.nodata
        if valid_fn is not None:
            valid &= valid_fn(a)
        inside = rasterize([(geom, 1)], out_shape=a.shape, transform=tr, fill=0, dtype="uint8").astype(bool)
        total = int(inside.sum())
        m = inside & valid
        cnt = int(m.sum())
        return (float(a[m].mean()) if cnt else float("nan")), cnt, total


def _sample_point(path: Path, lon: float, lat: float) -> float | None:
    with rasterio.open(path) as ds:
        v = float(next(ds.sample([(lon, lat)]))[0])
        if not np.isfinite(v) or (ds.nodata is not None and v == ds.nodata):
            return None
        return v


def live_cell_values(geom, centroid: tuple[float, float]) -> dict[str, Any]:
    """Cell means of every layer from the CURRENT GeoTIFFs (the ones on the map), computed on
    request with the same validity rules as the ML snapshot. The ML results keep their own
    snapshot; these are what the cell looks like now. None = not enough valid data, never 0."""
    S = _manifest()
    out: dict[str, Any] = {"ndvi": None, "ndvi_land": None, "lst": None, "water_health_score": None, "aqi": None,
                           "composite": None, "files": {}}

    def ok(st):
        return st is not None and st[1] > 0 and st[1] >= MIN_VALID_FRACTION * max(st[2], 1)

    p = _tif(S.get("ndvi"), "ndvi")
    if p:
        st = _cell_window_stats(p, geom)
        out["ndvi"] = round(st[0], 4) if ok(st) else None
        # vegetation of the LAND only (NDVI >= 0): open water's negative NDVI would otherwise pull an
        # area with a lake or creek towards "no vegetation" (same rule as the ndvi_land_mean feature)
        land = _cell_window_stats(p, geom, lambda a: a >= 0)
        out["ndvi_land"] = round(land[0], 4) if out["ndvi"] is not None and land[1] > 0 else None
        out["files"]["ndvi"] = p.name
    p = _tif(S.get("lst"), "lst")
    if p:
        st = _cell_window_stats(p, geom, lambda a, t=lst_qc_min_c(): a >= t)
        out["lst"] = round(st[0], 2) if ok(st) else None
        out["files"]["lst"] = p.name
    p = _tif(S.get("water_health"), "water-health")
    if p:
        st = _cell_window_stats(p, geom)
        out["water_health_score"] = round(st[0], 4) if st and st[1] >= MIN_WATER_PIXELS else None
        out["files"]["water_health"] = p.name
    p = _tif(S.get("aqi"), "aqi")
    from app.services.surfaces.aqi_station_surface import aqi_expired
    if p and (S.get("aqi") or {}).get("generation_status") == "generated" and not aqi_expired(S["aqi"]):
        st = _cell_window_stats(p, geom)
        if st and st[1] > 0:
            out["aqi"] = int(round(st[0]))
        else:   # the AQI grid is coarser than a cell: use the grid value at the cell centre
            v = _sample_point(p, *centroid)
            out["aqi"] = None if v is None else int(round(v))
        out["files"]["aqi"] = p.name
        out["aqi_generated_at"] = S["aqi"].get("generated_at")
    rec = S.get("composite") or {}
    cp = SURFACE_ROOT / rec["components_filename"] if rec.get("components_filename") else None
    if cp and cp.exists():
        from app.services.composite_v2 import COMPONENTS, WEIGHTS, contributions
        w, s, e, n = geom.bounds
        vals = {}
        with rasterio.open(cp) as ds:
            win = _cover_window(ds, w, s, e, n)
            tr = ds.window_transform(win)
            inside = rasterize([(geom, 1)], out_shape=(int(win.height), int(win.width)), transform=tr,
                               fill=0, dtype="uint8").astype(bool)
            for i, k in enumerate(COMPONENTS, start=1):
                a = ds.read(i, window=win).astype("float32")
                m = inside & np.isfinite(a) & (a != ds.nodata)
                vals[k] = float(a[m].mean()) if m.sum() >= MIN_VALID_FRACTION * max(int(inside.sum()), 1) and m.any() else None
        b = contributions(vals, rec.get("weights") or WEIGHTS)
        if b:
            out["composite"] = b
        out["files"]["composite"] = cp.name
    elif rec.get("generation_status", "generated") == "generated" and rec.get("geotiff_filename") \
            and (SURFACE_ROOT / rec["geotiff_filename"]).exists():
        # no per-component file (older composite): the cell mean of the composite score itself
        cpath = SURFACE_ROOT / rec["geotiff_filename"]
        st = _cell_window_stats(cpath, geom)
        if ok(st):
            out["composite"] = {"score": round(st[0], 3), "coverage": None, "components": {}, "missing": []}
        out["files"]["composite"] = cpath.name
    return out
