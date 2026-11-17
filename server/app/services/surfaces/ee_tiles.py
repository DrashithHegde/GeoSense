"""Split an Earth Engine download into tiles small enough for one request.

`Image.getDownloadURL` refuses a request of more than 48 MiB (50,331,648 bytes). A fixed two-tile
split worked for Mumbai but not for a larger city (Delhi at 10 m is ~26 million pixels), so the
number of tiles now follows the area, the pixel size and a conservative bytes-per-pixel estimate.
The tile edges are snapped to whole pixels so neighbouring tiles line up exactly when mosaicked.
"""
from __future__ import annotations

import math

EE_REQUEST_LIMIT_BYTES = 50_331_648
# Earth Engine's own accounting was ~5.7 bytes per pixel for a one-band float32 image, so use 6.
DEFAULT_BYTES_PER_PIXEL = 6.0
DEFAULT_MAX_TILE_BYTES = 40_000_000          # ~20 % below the limit
METRES_PER_DEGREE = 111_319.49079327358      # at the equator; Earth Engine converts `scale` in EPSG:4326 this way


def tile_grid(west: float, south: float, east: float, north: float, scale_m: float, *,
              bytes_per_pixel: float = DEFAULT_BYTES_PER_PIXEL,
              max_tile_bytes: float = DEFAULT_MAX_TILE_BYTES) -> list[tuple[str, float, float, float, float]]:
    """Return [(label, west, south, east, north), ...] covering the box, each tile under the size limit."""
    if not (east > west and north > south):
        raise ValueError("empty download region")
    lat0 = (south + north) / 2.0
    width_m = (east - west) * METRES_PER_DEGREE * math.cos(math.radians(lat0))
    height_m = (north - south) * METRES_PER_DEGREE
    total_bytes = (width_m / scale_m) * (height_m / scale_m) * bytes_per_pixel
    need = max(1, math.ceil(total_bytes / max_tile_bytes))

    best = None
    for cols in range(1, need + 1):
        rows = math.ceil(need / cols)
        tile_w, tile_h = width_m / cols, height_m / rows
        score = (cols * rows, abs(math.log(max(tile_w, 1.0) / max(tile_h, 1.0))))   # fewest tiles, then squarest
        if best is None or score < best[0]:
            best = (score, cols, rows)
    _, cols, rows = best

    pixel_deg = scale_m / METRES_PER_DEGREE

    def edges(lo: float, hi: float, parts: int) -> list[float]:
        n_pix = max(1, round((hi - lo) / pixel_deg))
        cuts = [lo + round(n_pix * i / parts) * pixel_deg for i in range(parts)]
        return cuts + [hi]

    xs, ys = edges(west, east, cols), edges(south, north, rows)
    return [(f"tile_r{r}_c{c}", xs[c], ys[r], xs[c + 1], ys[r + 1]) for r in range(rows) for c in range(cols)]