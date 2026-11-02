import requests
from shapely.geometry import shape
import json
import math

def get_area_km2(geom):
    # Equal area projection approx for Mumbai (Lat ~19)
    # 1 degree lat = ~111 km
    # 1 degree lon = ~111 * cos(19) = ~105 km
    # So 1 sq degree = ~ 11655 km2
    return geom.area * 11655

queries = [
    ("mumbai", "Greater Mumbai, Maharashtra, India", "Mumbai"),
    ("mumbai_mc", "Brihanmumbai Municipal Corporation, Maharashtra", "BMC"),
    ("mumbai_city", "Mumbai City, Maharashtra", "Mumbai City"),
    ("mumbai_sub", "Mumbai Suburban, Maharashtra", "Mumbai Suburban"),
    ("thane", "Thane Municipal Corporation, Maharashtra, India", "Thane MC"),
    ("thane_city", "Thane, Maharashtra, India", "Thane City"),
    ("mira_bhayandar", "Mira Bhayandar, Maharashtra, India", "Mira-Bhayandar Point"),
    ("mira_bhayandar_mc", "Mira Bhayandar Municipal Corporation, Maharashtra", "MBMC")
]

print(f"{'Query Name':<25} | {'Type':<15} | {'Area (km2)':<10} | {'Bounds (minx, miny, maxx, maxy)'}")
print("-" * 100)

for slug, q, name in queries:
    try:
        resp = requests.get(
            'https://nominatim.openstreetmap.org/search', 
            params={'q': q, 'format': 'geojson', 'polygon_geojson': 1, 'limit': 1}, 
            headers={'User-Agent': 'GeoSense/1.0'}
        )
        feats = resp.json().get('features', [])
        if feats:
            geom_type = feats[0]["geometry"]["type"]
            geom = shape(feats[0]["geometry"])
            area = get_area_km2(geom)
            bounds = tuple(round(b, 4) for b in geom.bounds)
            print(f"{name:<25} | {geom_type:<15} | {area:<10.2f} | {bounds}")
        else:
            print(f"{name:<25} | {'NOT FOUND':<15} | {'-':<10} | -")
    except Exception as e:
        print(f"{name:<25} | {'ERROR':<15} | {'-':<10} | -")

