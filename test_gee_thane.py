import sys
import os
sys.path.insert(0, os.path.abspath("server"))
from gee.gee_client import initialize_ee
initialize_ee()
import ee
import requests

bbox = ee.Geometry.Rectangle([72.95, 19.20, 73.05, 19.25])
l8 = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2').filterDate('2026-07-02', '2026-08-16').filterBounds(bbox)
l9 = ee.ImageCollection('LANDSAT/LC09/C02/T1_L2').filterDate('2026-07-02', '2026-08-16').filterBounds(bbox)

def mask_landsat_l2(image):
    qa = image.select("QA_PIXEL")
    clear = qa.bitwiseAnd(1 << 0).eq(0).And(qa.bitwiseAnd(1 << 3).eq(0)).And(qa.bitwiseAnd(1 << 4).eq(0))
    return image.updateMask(clear)

def add_lst_celsius(image):
    lst_c = image.select("ST_B10").multiply(0.00341802).add(149.0).subtract(273.15).rename("LST")
    return image.addBands(lst_c)

processed = l8.merge(l9).map(mask_landsat_l2).map(add_lst_celsius)
median = processed.median().select("LST")

url = median.getDownloadURL({
    'scale': 30,
    'crs': 'EPSG:4326',
    'region': bbox,
    'format': 'GEO_TIFF'
})
print("Download URL:", url)

resp = requests.get(url)
with open('test_thane.tif', 'wb') as f:
    f.write(resp.content)

import rasterio
import numpy as np
with rasterio.open('test_thane.tif') as src:
    data = src.read(1)
    valid = np.sum((data != src.nodata) & np.isfinite(data))
    print("Total pixels:", data.size)
    print("Valid pixels:", valid)
