import json
import math
import sys
import pathlib
import warnings

# Suppress Shapely deprecation warnings for clean output
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

from shapely.geometry import shape, Point
from shapely.ops import unary_union
import requests

# 1. Load Zones
zones_path = pathlib.Path(r"C:\Users\DRASHITH HEGDE\OneDrive\Desktop\GeoSense\server\scripts\generated_zones.geojson")
with open(zones_path, 'r', encoding='utf-8') as f:
    zones_fc = json.load(f)

features = zones_fc.get("features", [])
print(f"Total features: {len(features)}")
crs = zones_fc.get("crs", "Unknown (assumed EPSG:4326)")
print(f"CRS: {crs}")

zone_geoms = []
centroids = []
for idx, f in enumerate(features):
    geom = shape(f["geometry"])
    zone_geoms.append({
        "id": f.get("properties", {}).get("zone_id", idx),
        "geom": geom,
        "centroid": geom.centroid
    })
    centroids.append(geom.centroid)

# 2. Fetch Study Boundaries (using same logic as municipality_aggregation.py)
MMR_QUERIES = (
    ("mumbai",         "Greater Mumbai, Maharashtra, India",              "Mumbai"),
    ("thane",          "Thane Municipal Corporation, Maharashtra, India", "Thane"),
    ("mira_bhayandar", "Mira Bhayandar, Maharashtra, India",             "Mira-Bhayandar"),
)
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

municipalities = {}
study_geoms = []
for slug, query, display_name in MMR_QUERIES:
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={"q": query, "format": "geojson", "polygon_geojson": 1, "limit": 1},
            headers={"User-Agent": "GeoSense/1.0"},
            timeout=30,
        )
        resp.raise_for_status()
        feats = resp.json().get("features", [])
        if feats and feats[0].get("geometry", {}).get("type") in ("Polygon", "MultiPolygon"):
            geom = shape(feats[0]["geometry"]).simplify(0.0005, preserve_topology=True)
            municipalities[slug] = {"name": display_name, "geom": geom}
            study_geoms.append(geom)
    except Exception as e:
        print(f"Failed to fetch {display_name}: {e}")

combined_boundary = unary_union(study_geoms)

# 3. Zone Coverage
inside = []
intersecting = []
outside = []

muni_counts = {slug: 0 for slug in municipalities.keys()}

for z in zone_geoms:
    geom = z["geom"]
    if combined_boundary.contains(geom):
        inside.append(z)
    elif combined_boundary.intersects(geom):
        intersecting.append(z)
    else:
        outside.append(z)
        
    for slug, m in municipalities.items():
        if m["geom"].intersects(geom):
            muni_counts[slug] += 1

print(f"Coverage: Inside={len(inside)}, Intersecting={len(intersecting)}, Outside={len(outside)}")
print(f"Percentage Coverage: {((len(inside) + len(intersecting))/len(features))*100:.1f}%")
print("Municipality Counts:")
for slug, count in muni_counts.items():
    print(f"  {municipalities[slug]['name']}: {count}")

# 4. Spatial Distribution (Nearest Neighbor)
# We calculate approx distance using Haversine
def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

nn_distances = []
for i, c1 in enumerate(centroids):
    min_dist = float('inf')
    for j, c2 in enumerate(centroids):
        if i == j: continue
        d = haversine_m(c1.y, c1.x, c2.y, c2.x)
        if d < min_dist:
            min_dist = d
    nn_distances.append(min_dist)

import statistics
if nn_distances:
    print(f"NN Min: {min(nn_distances):.1f}m")
    print(f"NN Max: {max(nn_distances):.1f}m")
    print(f"NN Mean: {statistics.mean(nn_distances):.1f}m")
    print(f"NN Median: {statistics.median(nn_distances):.1f}m")

# Determine max distance from any point in boundary to nearest zone
bbox = combined_boundary.bounds # minx, miny, maxx, maxy
xs = [bbox[0] + (bbox[2]-bbox[0])*i/20.0 for i in range(21)]
ys = [bbox[1] + (bbox[3]-bbox[1])*i/20.0 for i in range(21)]

max_gap = 0
for x in xs:
    for y in ys:
        p = Point(x, y)
        if combined_boundary.contains(p):
            min_d = min(haversine_m(y, x, c.y, c.x) for c in centroids)
            if min_d > max_gap:
                max_gap = min_d
print(f"Max gap in study area to nearest zone centroid: {max_gap:.1f}m")

