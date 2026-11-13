"""Build GeoSense's seasonal history (run on your machine; needs Earth Engine + OpenAQ key).

    python scripts/build_history.py                 # satellites + stations, all seasons since 2023
    python scripts/build_history.py --only satellite
    python scripts/build_history.py --only stations
    python scripts/build_history.py --rebuild        # recompute seasons already on disk

Resumable: a season whose CSV already exists is loaded from disk, not recomputed (except the
season still in progress and its matched window, which are always refreshed).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
for p in (str(SERVER_ROOT.parent), str(SERVER_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.services.history.seasons import seasons  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", choices=["satellite", "stations"])
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--first-year", type=int, default=2023)
    a = ap.parse_args()

    from app.database import SessionLocal
    from app.services.history import analytics, store
    from app.services.history.gee_builder import HISTORY_DIR, build_season

    season_list = seasons(date.today(), a.first_year)
    print("Seasons:", ", ".join(s.key + (" (partial)" if s.partial else "") for s in season_list))
    db = SessionLocal()
    try:
        if a.only in (None, "satellite"):
            import ee

            from app.services.municipality_boundaries import get_study_region_bounds
            from gee.cell_reducer import load_cell_polygons
            from gee.gee_client import initialize_ee

            initialize_ee()
            region = ee.Geometry.Rectangle(list(get_study_region_bounds()), proj="EPSG:4326", geodesic=False)
            cells = load_cell_polygons(db)
            meta_path = HISTORY_DIR / "seasons.json"
            metas = json.loads(meta_path.read_text()) if meta_path.exists() else {}
            for s in season_list:
                csv_path = HISTORY_DIR / f"cells_{s.key}.csv"
                fresh = s.partial or s.matched_for
                if csv_path.exists() and s.key in metas and not (a.rebuild or fresh):
                    print(f"{s.key}: on disk, loading")
                else:
                    print(f"{s.key}: computing in Earth Engine ({s.start} → {s.end})")
                    metas[s.key] = build_season(s, cells, region)
                    meta_path.write_text(json.dumps(metas, indent=2), encoding="utf-8")
                store.upsert_season(db, metas[s.key])
                n = store.load_cell_csv(db, s.key)
                db.commit()
                print(f"  {s.key}: {n} cells loaded · S2 images {metas[s.key]['s2_images']} · "
                      f"Landsat images {metas[s.key]['landsat_images']}")
        if a.only in (None, "stations"):
            from app.core.config import get_settings
            from app.services.history.station_history import build_station_history

            key = get_settings().openaq_aqi_key or os.getenv("OPENAQ_AQI_KEY")
            if not key:
                print("No OpenAQ key (OPENAQ_AQI_KEY) — skipping station history.")
            else:
                for s in season_list:   # seasons table must exist for labels
                    store.upsert_season(db, {"season": s.key, "label": s.label, "kind": s.kind, "year": s.year,
                                             "period_start": s.start.isoformat(), "period_end": s.end.isoformat(),
                                             "partial": s.partial, "matched_for": s.matched_for})
                db.commit()
                rows = build_station_history(key, season_list)
                print(f"Station seasons stored: {store.upsert_station_rows(db, rows)}")
                db.commit()
        summary = analytics.build_summary(db)
        ci = summary.get("change_isolation_forest") or {}
        print(json.dumps({"seasons": [s["season"] for s in summary["seasons"]],
                          "latest_pair": summary.get("latest_pair"),
                          "change_isolation_forest": {k: ci.get(k) for k in ("status", "pair", "eligible", "anomalies")}},
                         indent=2))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
