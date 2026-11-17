"""Earth Engine zonal statistics over the 300 m analytical cells.

Sends the spatial_cells polygons to Earth Engine in batches and runs reduceRegions at the
source band's native scale, so the statistics are computed on the original pixels (no
download of full rasters needed). Used by the ESA WorldCover validation reference and by the
seasonal history builder.
"""
from __future__ import annotations

import time
from typing import Any, Iterable

from shapely import wkb
from sqlalchemy import text

BATCH = 1000


def load_cell_polygons(db) -> list[tuple[int, list]]:
    """The current city's cells (id, exterior ring)."""
    from app.core.cities import current_city_id
    rows = db.execute(text("SELECT id, ST_AsBinary(geometry) AS g FROM spatial_cells WHERE city = :city ORDER BY id"),
                      {"city": current_city_id()}).mappings().all()
    out = []
    for r in rows:
        g = wkb.loads(bytes(r["g"]))
        poly = g if g.geom_type == "Polygon" else max(g.geoms, key=lambda p: p.area)
        out.append((int(r["id"]), [list(c) for c in poly.exterior.coords]))
    return out


def _batches(items: list, size: int) -> Iterable[list]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def reduce_cells(image, reducer, scale: float, cells: list[tuple[int, list]], *, batch: int = BATCH,
                 tile_scale: int = 4, label: str = "") -> list[dict[str, Any]]:
    """Run image.reduceRegions over every cell; returns one property dict per cell (with cell_id)."""
    import ee

    out: list[dict[str, Any]] = []
    for n, chunk in enumerate(_batches(cells, batch), start=1):
        fc = ee.FeatureCollection([ee.Feature(ee.Geometry.Polygon([coords], proj="EPSG:4326", geodesic=False),
                                              {"cell_id": cid}) for cid, coords in chunk])
        res = image.reduceRegions(collection=fc, reducer=reducer, scale=scale, tileScale=tile_scale)
        for attempt in range(4):
            try:
                feats = res.getInfo()["features"]
                break
            except Exception as exc:  # transient EE errors: back off and retry
                if attempt == 3:
                    raise
                print(f"  {label} batch {n}: {exc!s:.120} — retrying")
                time.sleep(5 * (attempt + 1))
        out.extend(f["properties"] for f in feats)
        print(f"  {label} batch {n}: {len(out)}/{len(cells)} cells")
    return out
