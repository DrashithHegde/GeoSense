import os
import sys
import requests
from pathlib import Path
import ee

sys.path.insert(0, os.path.abspath("server"))
from gee.gee_client import initialize_ee
from app.services.surfaces.lst_surface import (
    get_lst_export_bounds,
    build_lst_composite,
    publish_lst_geotiff,
    CRS,
    NODATA_VALUE
)

def regenerate():
    initialize_ee()
    
    bounds = get_lst_export_bounds()
    print("New export bounds:", bounds)
    
    start_date = "2026-07-02"
    end_date = "2026-08-16"
    
    composite = build_lst_composite(start_date=start_date, end_date=end_date, bounds=bounds)
    
    # UNMASK to prevent GEE from defaulting to 0 for masked pixels
    composite = composite.unmask(NODATA_VALUE)
    
    region = ee.Geometry.Rectangle(list(bounds), proj=CRS, geodesic=False)
    
    print("Requesting download URL...")
    url = composite.getDownloadURL({
        'scale': 30,
        'crs': CRS,
        'region': region,
        'format': 'GEO_TIFF'
    })
    
    print("Downloading TIF...")
    resp = requests.get(url)
    resp.raise_for_status()
    
    temp_tif = Path("temp_new_lst.tif")
    temp_tif.write_bytes(resp.content)
    print("Saved to temp_new_lst.tif")
    
    print("Publishing surface...")
    record = publish_lst_geotiff(
        temp_tif,
        start_date=start_date,
        end_date=end_date,
        image_count=0
    )
    
    print("Regeneration complete!")
    print(record)

if __name__ == "__main__":
    regenerate()
