"""Build a city's boundary file from DataMeet's Municipal Spatial Data (real, published boundaries).

    python scripts/import_city_boundaries.py --city delhi
    python scripts/import_city_boundaries.py --city bengaluru
    python scripts/import_city_boundaries.py --city delhi --source path/to/Delhi_Boundary.geojson   (offline)

Delhi     : Delhi_Boundary.geojson — the National Capital Territory boundary
Bengaluru : BBMP.geojson — the 243 BBMP wards (2022 delimitation, KSRSAC), dissolved into one area

Writes data/cities/<city>/boundaries/<city>.geojson (one Feature, properties.id = city id), the
format app/services/municipality_boundaries.py expects. Data: DataMeet Municipal Spatial Data,
https://github.com/datameet/Municipal_Spatial_Data, CC BY-SA 2.5 India — keep the attribution.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT))

from shapely.geometry import MultiPolygon, Polygon, mapping, shape  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

from app.core.cities import get_city  # noqa: E402

RAW = "https://raw.githubusercontent.com/datameet/Municipal_Spatial_Data/master/"
SOURCES = {
    "delhi": {"file": "Delhi/Delhi_Boundary.geojson",
              "what": "National Capital Territory of Delhi boundary",
              "origin": "scraped by DataMeet from an ArcGIS Online map (item 7c4f1b9be6cc4cecbcd28ee5136898f7)"},
    "bengaluru": {"file": "Bangalore/BBMP.geojson",
                  "what": "BBMP area: 243 wards (2022 delimitation) dissolved",
                  "origin": "BBMP wards from KSRSAC Bengaluru GIS (kgis.ksrsac.in), via DataMeet"},
}
LICENSE = "CC BY-SA 2.5 India (DataMeet Municipal Spatial Data)"


def _load(src: str) -> dict:
    if src.startswith("http"):
        import requests
        r = requests.get(src, timeout=60)
        r.raise_for_status()
        return r.json()
    return json.loads(Path(src).read_text(encoding="utf-8"))


def build(city_id: str, source: str | None = None) -> Path:
    city = get_city(city_id)
    meta = SOURCES[city.id]
    fc = _load(source or RAW + meta["file"])
    geoms = [shape(f["geometry"]).buffer(0) for f in fc["features"] if f.get("geometry")]
    geom = unary_union(geoms)
    # dissolved wards leave slivers between neighbours: close them with a tiny buffer out and back
    geom = geom.buffer(0.0001).buffer(-0.0001)
    if geom.geom_type == "Polygon":
        geom = Polygon(geom.exterior)
    else:  # keep real separate parts, fill interior slivers
        geom = MultiPolygon([Polygon(p.exterior) for p in geom.geoms if p.area > 1e-7])
    if geom.is_empty or not geom.is_valid:
        raise SystemExit(f"{city.name}: dissolved boundary is invalid")
    (mid, name), = city.municipalities
    feature = {"type": "Feature", "properties": {
        "id": mid, "name": name, "city": city.id, "description": meta["what"],
        "source": f"{meta['origin']}; {RAW}{meta['file']}", "license": LICENSE,
        "features_dissolved": len(geoms), "imported_at": datetime.now(timezone.utc).date().isoformat()},
        "geometry": mapping(geom)}
    out = city.data_dir / "boundaries" / f"{mid}.geojson"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"type": "FeatureCollection", "features": [feature]}), encoding="utf-8")
    import math
    lat = (geom.bounds[1] + geom.bounds[3]) / 2
    km2 = geom.area * 111.32 ** 2 * math.cos(math.radians(lat))
    print(f"{city.name}: {len(geoms)} source polygon(s) -> {geom.geom_type}, ~{km2:,.0f} km², "
          f"bounds {tuple(round(b, 4) for b in geom.bounds)} -> {out}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--city", required=True, choices=sorted(SOURCES))
    ap.add_argument("--source", help="local copy of the DataMeet GeoJSON (default: download from GitHub)")
    a = ap.parse_args()
    build(a.city, a.source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
