import requests

MMR_QUERIES = [
    ("mumbai", "Greater Mumbai, Maharashtra, India", "Mumbai"),
    ("thane", "Thane Municipal Corporation, Maharashtra, India", "Thane"),
    ("mira_bhayandar", "Mira Bhayandar, Maharashtra, India", "Mira-Bhayandar")
]

for slug, query, name in MMR_QUERIES:
    resp = requests.get('https://nominatim.openstreetmap.org/search', params={'q': query, 'format': 'geojson', 'polygon_geojson': 1, 'limit': 1}, headers={'User-Agent': 'GeoSense/1.0'})
    feats = resp.json().get('features', [])
    if feats:
        print(name, "Found", feats[0]["geometry"]["type"])
    else:
        print(name, "Not found")
