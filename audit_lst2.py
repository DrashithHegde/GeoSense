import os
import json
import urllib.request
from pathlib import Path

def test_api(name, lon, lat):
    url = f"http://localhost:8000/api/surfaces/lst/value?lon={lon}&lat={lat}"
    try:
        resp = urllib.request.urlopen(url).read().decode()
        data = json.loads(resp)
        print(f"  {name}: {data['value_c']} (nodata: {data['nodata']})")
    except Exception as e:
        print(f"  {name}: Failed - {e}")

print("--- Testing API ---")
test_api("Mumbai", 72.8777, 19.0760)
test_api("Mira-Bhayandar", 72.8593, 19.2952)
test_api("Thane", 72.9781, 19.2183)
test_api("Outside (Arabian Sea)", 72.0000, 19.0000)

print("\n--- Manifest Info ---")
SERVER_ROOT = Path("server").resolve()
manifest_path = SERVER_ROOT / "data" / "surfaces" / "manifest.json"
with open(manifest_path, "r") as f:
    manifest = json.load(f)

lst = manifest["surfaces"]["lst"]
print(f"Bounds: {lst['bounds']}")
print(f"Coordinates: {lst['coordinates']}")
print(f"Min: {lst['lst_min_c']}")
print(f"Max: {lst['lst_max_c']}")
print(f"Mean: {lst['lst_mean_c']}")
print(f"Valid pixels: {lst['valid_pixels']}")
print(f"Units: {lst['unit']}")
print(f"Resolution: {lst['scale_m']}")
print(f"GeoTIFF: {lst['files']['geotiff']}")
print(f"PNG: {lst['files']['png']}")
print(f"Glow: {lst['files']['glow_png']}")

# We will also read from geotiff directly to compare
import rasterio
from rasterio.windows import Window
import numpy as np

tif_path = SERVER_ROOT / "data" / "surfaces" / "lst" / lst["files"]["geotiff"]
print("\n--- GeoTIFF Direct Check ---")
with rasterio.open(tif_path) as dataset:
    print(f"CRS: {dataset.crs}")
    print(f"Dimensions: {dataset.width}x{dataset.height}")
    print(f"NoData: {dataset.nodata}")
    
    coords = [
        ("Mumbai", 72.8777, 19.0760),
        ("Mira-Bhayandar", 72.8593, 19.2952),
        ("Thane", 72.9781, 19.2183)
    ]
    for name, lon, lat in coords:
        row, col = dataset.index(lon, lat)
        val = dataset.read(1, window=Window(col, row, 1, 1))[0, 0]
        print(f"  {name} Direct: {val:.2f}")

