import json
with open('server/data/boundaries/thane.geojson') as f:
    data = json.load(f)
coords = data['features'][0]['geometry']['coordinates'][0]
if isinstance(coords[0][0], list):
    # MultiPolygon
    lons = [c[0] for part in data['features'][0]['geometry']['coordinates'] for poly in part for c in poly]
    lats = [c[1] for part in data['features'][0]['geometry']['coordinates'] for poly in part for c in poly]
else:
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
print(f"Thane Bounds: W={min(lons):.4f}, E={max(lons):.4f}, S={min(lats):.4f}, N={max(lats):.4f}")

with open('server/data/boundaries/mira_bhayandar.geojson') as f:
    data = json.load(f)
coords = data['features'][0]['geometry']['coordinates'][0]
if isinstance(coords[0][0], list):
    lons = [c[0] for part in data['features'][0]['geometry']['coordinates'] for poly in part for c in poly]
    lats = [c[1] for part in data['features'][0]['geometry']['coordinates'] for poly in part for c in poly]
else:
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
print(f"MB Bounds: W={min(lons):.4f}, E={max(lons):.4f}, S={min(lats):.4f}, N={max(lats):.4f}")
