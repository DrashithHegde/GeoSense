"""Load seasonal history into PostgreSQL (history_seasons, cell_history, station_aqi_history)."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.core.cities import current_city_id
from app.services.history.gee_builder import COLUMNS, HISTORY_DIR


def _f(v):
    if v in (None, "", "None", "nan"):
        return None
    return float(v)


def upsert_season(db, meta: dict[str, Any]) -> None:
    db.execute(text("""
        INSERT INTO history_seasons (city, season, label, kind, year, period_start, period_end, partial,
                                     s2_images, landsat_images, metadata, generated_at)
        VALUES (:city, :season, :label, :kind, :year, :ps, :pe, :partial, :s2, :ls, CAST(:meta AS jsonb), now())
        ON CONFLICT (city, season) DO UPDATE SET label = EXCLUDED.label, period_start = EXCLUDED.period_start,
            period_end = EXCLUDED.period_end, partial = EXCLUDED.partial,
            s2_images = COALESCE(EXCLUDED.s2_images, history_seasons.s2_images),
            landsat_images = COALESCE(EXCLUDED.landsat_images, history_seasons.landsat_images),
            metadata = COALESCE(history_seasons.metadata, '{}'::jsonb) || EXCLUDED.metadata, generated_at = now()
    """), {"city": current_city_id(), "season": meta["season"], "label": meta["label"], "kind": meta["kind"], "year": meta["year"],
           "ps": meta["period_start"], "pe": meta["period_end"], "partial": bool(meta.get("partial")),
           "s2": meta.get("s2_images"), "ls": meta.get("landsat_images"), "meta": json.dumps(meta)})


def load_cell_csv(db, season: str, path: Path | None = None) -> int:
    path = path or HISTORY_DIR / f"cells_{season}.csv"
    with path.open(encoding="utf-8") as f:
        rows = [{"city": current_city_id(), "season": season, **{k: (int(r[k]) if k == "cell_id" else _f(r.get(k))) for k in COLUMNS}}
                for r in csv.DictReader(f)]
    if not rows:
        return 0
    cols = ", ".join(COLUMNS)
    vals = ", ".join(f":{c}" for c in COLUMNS)
    upd = ", ".join(f"{c} = EXCLUDED.{c}" for c in COLUMNS if c != "cell_id")
    db.execute(text(f"""
        INSERT INTO cell_history (city, season, {cols}) VALUES (:city, :season, {vals})
        ON CONFLICT (cell_id, season) DO UPDATE SET {upd}
    """), rows)
    return len(rows)


def upsert_station_rows(db, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    db.execute(text("""
        INSERT INTO station_aqi_history (city, station_id, station_name, lat, lon, season, days_with_aqi, aqi_median,
                                         aqi_p90, dominant_pollutant, sub_index_medians, method)
        VALUES (:city, :station_id, :station_name, :lat, :lon, :season, :days_with_aqi, :aqi_median, :aqi_p90,
                :dominant_pollutant, CAST(:subs AS jsonb), :method)
        ON CONFLICT (city, station_id, season) DO UPDATE SET days_with_aqi = EXCLUDED.days_with_aqi,
            aqi_median = EXCLUDED.aqi_median, aqi_p90 = EXCLUDED.aqi_p90,
            dominant_pollutant = EXCLUDED.dominant_pollutant, sub_index_medians = EXCLUDED.sub_index_medians,
            method = EXCLUDED.method, station_name = EXCLUDED.station_name
    """), [{**r, "city": current_city_id(), "subs": json.dumps(r.get("sub_index_medians") or {})} for r in rows])
    return len(rows)
