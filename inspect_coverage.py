import json
import rasterio
from rasterio.features import geometry_mask
from pathlib import Path
import numpy as np

def calculate_coverage(tif_path, geojson_path):
    with open(geojson_path) as f:
        data = json.load(f)
        
    geometries = [feat['geometry'] for feat in data['features']]
    
    with rasterio.open(tif_path) as src:
        mask = geometry_mask(geometries, transform=src.transform, invert=True, out_shape=src.shape)
        data = src.read(1)
        
        inside_pixels = data[mask]
        total = inside_pixels.size
        if total == 0:
            return 0, 0, 0, 0.0
            
        nodata = np.sum((inside_pixels == src.nodata) | ~np.isfinite(inside_pixels))
        valid = total - nodata
        return total, valid, nodata, (valid / total * 100)

tif = Path("server/data/surfaces/lst/lst_20260816T000000Z.tif")
boundaries = [
    ("Mumbai", "server/data/boundaries/mumbai.geojson"),
    ("Mira-Bhayandar", "server/data/boundaries/mira_bhayandar.geojson"),
    ("Thane", "server/data/boundaries/thane.geojson")
]

for name, bp in boundaries:
    t, v, n, pct = calculate_coverage(tif, bp)
    print(f"{name}: Total={t}, Valid={v}, NoData={n}, Valid%={pct:.2f}%")
