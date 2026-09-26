import os
import sys
import json
import asyncio
from pathlib import Path
import rasterio
from rasterio.windows import Window
import numpy as np
import httpx

sys.path.insert(0, os.path.abspath("server"))
from app.api.routes import get_lst_pixel_value, load_latest_lst_surface

async def run_audit():
    SERVER_ROOT = Path("server").resolve()
    manifest_path = SERVER_ROOT / "data" / "surfaces" / "manifest.json"
    
    with open(manifest_path, "r") as f:
        manifest = json.load(f)
        
    lst_info = manifest["surfaces"]["lst"]
    
    tif_path = SERVER_ROOT / "data" / "surfaces" / "lst" / lst_info["files"]["geotiff"]
    png_path = SERVER_ROOT / "data" / "surfaces" / "lst" / lst_info["files"]["png"]
    glow_path = SERVER_ROOT / "data" / "surfaces" / "lst" / lst_info["files"]["glow_png"]
    
    print(f"Backend Files:")
    print(f"GeoTIFF path: {tif_path} (Exists: {tif_path.exists()})")
    print(f"PNG path: {png_path} (Exists: {png_path.exists()})")
    print(f"Glow PNG path: {glow_path} (Exists: {glow_path.exists()})")
    
    with rasterio.open(tif_path) as dataset:
        print("\nRaster metadata:")
        print(f"Dimensions: {dataset.width} x {dataset.height}")
        print(f"CRS: {dataset.crs}")
        print(f"Resolution: {dataset.res}")
        print(f"Bounds: {dataset.bounds}")
        print(f"NoData: {dataset.nodata}")
        
        # Test values
        coords = [
            ("Mumbai", 72.8777, 19.0760),
            ("Mira-Bhayandar", 72.8593, 19.2952),
            ("Thane", 72.9781, 19.2183),
            ("Outside (Arabian Sea)", 72.0000, 19.0000)
        ]
        
        print("\nTesting Coordinates:")
        for name, lon, lat in coords:
            print(f"--- {name} ({lon}, {lat}) ---")
            
            # Check coverage
            in_bounds = (dataset.bounds.left <= lon <= dataset.bounds.right and dataset.bounds.bottom <= lat <= dataset.bounds.top)
            
            # Direct GeoTIFF read
            direct_val = None
            if in_bounds:
                row, col = dataset.index(lon, lat)
                if 0 <= row < dataset.height and 0 <= col < dataset.width:
                    val = dataset.read(1, window=Window(col, row, 1, 1))[0, 0]
                    if val != dataset.nodata and np.isfinite(val):
                        direct_val = val
            
            # API read
            api_res = await get_lst_pixel_value(lon, lat)
            api_val = api_res.get("value_c")
            api_nodata = api_res.get("nodata")
            
            print(f"Covered by bounds: {in_bounds}")
            print(f"Direct GeoTIFF value: {direct_val}")
            print(f"API value_c: {api_val} (nodata: {api_nodata})")
            
            if direct_val is not None and api_val is not None:
                diff = abs(direct_val - api_val)
                print(f"Difference: {diff}")
                
    print("\nManifest stats:")
    print(f"Units: {lst_info['unit']}")
    print(f"Min: {lst_info['lst_min_c']}")
    print(f"Max: {lst_info['lst_max_c']}")
    print(f"Mean: {lst_info['lst_mean_c']}")
    print(f"Valid pixels: {lst_info['valid_pixels']}")

if __name__ == "__main__":
    asyncio.run(run_audit())
