# -*- coding: utf-8 -*-
import ee
import logging
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def download_rasters():
    output_dir = './tiles/geotiffs'
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        ee.Initialize()
        logging.info("Earth Engine initialized successfully.")
    except Exception as e:
        logging.error(f"Failed to initialize Earth Engine: {e}")
        return

    # Mumbai bounding box
    bbox = ee.Geometry.Rectangle([72.77, 18.89, 72.95, 19.22])

    try:
        # Get Landsat 8 image (least cloudy of 2024 for Mumbai region)
        image = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2') \
            .filterBounds(bbox) \
            .filterDate('2024-01-01', '2024-12-31') \
            .filter(ee.Filter.lt('CLOUD_COVER', 30)) \
            .median() \
            .clip(bbox)
        
        # Calculate NDVI: (NIR - Red) / (NIR + Red)
        ndvi = image.normalizedDifference(['SR_B5', 'SR_B4']).rename('NDVI')
        
        # Calculate NDWI: (Green - NIR) / (Green + NIR)
        ndwi = image.normalizedDifference(['SR_B3', 'SR_B5']).rename('NDWI')
        
        # Calculate LST from Thermal Band 10 (convert from Kelvin to Celsius)
        # Landsat 8 C02 T1_L2 ST_B10 scale factor is 0.00341802 and offset is 149.0
        lst = image.select('ST_B10').multiply(0.00341802).add(149.0).subtract(273.15).rename('LST')

        logging.info("Starting downloads. This may take a few minutes...")

        # Function to download the images
        def download_image(img, name):
            url = img.getDownloadURL({
                'scale': 30,
                'crs': 'EPSG:4326',
                'region': bbox,
                'format': 'GEO_TIFF'
            })
            logging.info(f"Download URL for {name} ready: {url}")
            logging.info(f"Please download the {name} GeoTIFF using the link above.")

        import requests
        
        for name, img in [('NDVI', ndvi), ('NDWI', ndwi), ('LST', lst)]:
            logging.info(f"Requesting download URL for {name}...")
            url = img.getDownloadURL({
                'scale': 30,
                'crs': 'EPSG:4326',
                'region': bbox,
                'format': 'GEO_TIFF'
            })
            filepath = os.path.join(output_dir, f'mumbai_{name.lower()}.tif')
            logging.info(f"Downloading {name} to {filepath}...")
            response = requests.get(url)
            if response.status_code == 200:
                with open(filepath, 'wb') as f:
                    f.write(response.content)
                logging.info(f"Successfully saved {filepath}")
            else:
                logging.error(f"Failed to download {name}: Status code {response.status_code}")

        logging.info("All downloads completed.")
        
    except Exception as e:
        logging.error(f"Error during processing: {e}")

if __name__ == "__main__":
    download_rasters()