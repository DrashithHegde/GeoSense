import requests
from shapely.geometry import shape
import json
import pathlib

MMR_QUERIES = [
    ("mumbai", "Greater Mumbai, Maharashtra, India", "Mumbai"),
    ("thane", "Thane Municipal Corporation, Maharashtra, India", "Thane")
]

for slug, query, name in MMR_QUERIES:
    resp = requests.get('https://nominatim.openstreetmap.org/search', params={'q': query, 'format': 'geojson', 'polygon_geojson': 1, 'limit': 1}, headers={'User-Agent': 'GeoSense/1.0'})
    feats = resp.json().get('features', [])
    if feats:
        geom = shape(feats[0]["geometry"])
        print(name, "Bounds:", geom.bounds)

zones_path = pathlib.Path(r"C:\Users\DRASHITH HEGDE\OneDrive\Desktop\GeoSense\server\scripts\generated_zones.geojson")
with open(zones_path, 'r', encoding='utf-8') as f:
    zones_fc = json.load(f)

minx, miny, maxx, maxy = 180, 90, -180, -90
for f in zones_fc["features"]:
    g = shape(f["geometry"])
    b = g.bounds
    minx, miny = min(minx, b[0]), min(miny, b[1])
    maxx, maxy = max(maxx, b[2]), max(maxy, b[3])

print("Zones Bounds:", (minx, miny, maxx, maxy))
