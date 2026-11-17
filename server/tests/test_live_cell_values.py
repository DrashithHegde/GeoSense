"""live_cell_values: the 300 m cell's values from the CURRENT GeoTIFFs, with the ML snapshot's rules."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from app.services.ml import cell_features as cf

W, N, PX = 72.80, 19.20, 0.0005          # ~55 m pixels


def _tif(path: Path, arr: np.ndarray, nodata=-9999.0):
    with rasterio.open(path, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1,
                       dtype="float32", crs="EPSG:4326", transform=from_origin(W, N, PX, PX), nodata=nodata) as ds:
        ds.write(arr.astype("float32"), 1)


class LiveCellValuesTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        for d in ("ndvi", "lst", "aqi", "water-health"):
            (self.root / d).mkdir()
        shape = (40, 40)
        _tif(self.root / "ndvi" / "n.tif", np.full(shape, 0.4))
        lst = np.full(shape, 35.0)
        lst[:, :20] = 10.0                     # below the LST QC minimum: probable cloud -> excluded
        _tif(self.root / "lst" / "l.tif", lst)
        _tif(self.root / "aqi" / "a.tif", np.full(shape, 239.0))
        _tif(self.root / "water-health" / "w.tif", np.full(shape, -9999.0))   # no water at all
        self.manifest = {"surfaces": {
            "ndvi": {"generation_status": "generated", "files": {"geotiff": "n.tif"}},
            "lst": {"generation_status": "generated", "files": {"geotiff": "l.tif"}},
            "aqi": {"generation_status": "generated", "geotiff_filename": "aqi/a.tif", "generated_at": "now"},
            "water_health": {"generation_status": "generated", "files": {"geotiff": "w.tif"}},
        }}
        (self.root / "manifest.json").write_text(json.dumps(self.manifest))
        self._p = [mock.patch.object(cf, "SURFACE_ROOT", self.root),
                   mock.patch.object(cf, "MANIFEST", self.root / "manifest.json")]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def test_values_come_from_the_current_rasters(self):
        # a 300 m cell in the middle of the rasters
        lon, lat = W + 20 * PX, N - 20 * PX
        cell = box(lon - 0.0014, lat - 0.0014, lon + 0.0014, lat + 0.0014)
        out = cf.live_cell_values(cell, (lon, lat))
        self.assertAlmostEqual(out["ndvi"], 0.4, places=4)
        self.assertEqual(out["aqi"], 239)
        self.assertIsNone(out["water_health_score"])          # no water pixels -> None, never 0
        self.assertIsNone(out["composite"])                     # no composite in this manifest

    def test_lst_qc_and_min_valid_fraction(self):
        # a cell whose left half is "cloud" (below QC): 50% valid >= 30% -> mean of the valid half only
        lon, lat = W + 20 * PX, N - 20 * PX
        out = cf.live_cell_values(box(lon - 0.0014, lat - 0.0014, lon + 0.0014, lat + 0.0014), (lon, lat))
        self.assertAlmostEqual(out["lst"], 35.0, places=2)
        # a cell entirely in the cloudy half -> no LST value
        lon2 = W + 5 * PX
        out2 = cf.live_cell_values(box(lon2 - 0.0014, lat - 0.0014, lon2 + 0.0014, lat + 0.0014), (lon2, lat))
        self.assertIsNone(out2["lst"])


if __name__ == "__main__":
    unittest.main()
