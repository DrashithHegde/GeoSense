import requests, json
from shapely.geometry import shape

# rel/7965684 = Thane district (4241 km2) - WRONG - that's entire Thane district
# rel/7120000 = Thane Subdistrict - bbox [19.13-19.30, 72.91-73.08] - looks like Thane MC area
# rel/13180677 = Mira-Bhayander - bbox [19.23-19.33, 72.78-72.94] - looks RIGHT

# For Mumbai we need to find the actual BMC admin boundary
# BMC covers Mumbai City district + Mumbai Suburban district
# Let's search Nominatim specifically for Mumbai City District and Mumbai Suburban District

nom_lookup = "https://nominatim.openstreetmap.org/lookup"
nom_search = "https://nominatim.openstreetmap.org/search"

# Check area of rel/7120000 (Thane Subdistrict)
def get_area_km2(geom):
    return geom.area * 11655

resp = requests.get(nom_lookup,
    params={"osm_ids": "R7120000", "format": "json", "polygon_geojson": 1},
    headers={"User-Agent": "GeoSense/1.0"}, timeout=20)
r = resp.json()[0]
geom = shape(r["geojson"])
area = get_area_km2(geom)
print(f"rel/7120000 (Thane Subdistrict): area={area:.1f} km2, bbox={r['boundingbox']}")
print("  Thane MC actual area = ~147 km2 → too large if this is 1000+ km2")

# Check Mira-Bhayandar
resp2 = requests.get(nom_lookup,
    params={"osm_ids": "R13180677", "format": "json", "polygon_geojson": 1},
    headers={"User-Agent": "GeoSense/1.0"}, timeout=20)
r2 = resp2.json()[0]
geom2 = shape(r2["geojson"])
area2 = get_area_km2(geom2)
print(f"\nrel/13180677 (Mira-Bhayander): area={area2:.1f} km2, bbox={r2['boundingbox']}")
print("  Mira-Bhayandar MC actual area = ~79 km2")

# Now find Mumbai - try Mumbai City District and Mumbai Suburban District
print("\n=== SEARCHING FOR MUMBAI CITY/SUBURBAN DISTRICTS ===")
resp3 = requests.get(nom_search,
    params={"q": "Mumbai City District Maharashtra", "format": "json", "polygon_geojson": 0, "limit": 3},
    headers={"User-Agent": "GeoSense/1.0"}, timeout=20)
for r3 in resp3.json()[:3]:
    print(f"  {r3.get('osm_type')}/{r3.get('osm_id')} class={r3.get('class')} type={r3.get('type')} bb={r3.get('boundingbox')} name={r3.get('display_name','')[:60]}")

resp4 = requests.get(nom_search,
    params={"q": "Mumbai Suburban District Maharashtra", "format": "json", "polygon_geojson": 0, "limit": 3},
    headers={"User-Agent": "GeoSense/1.0"}, timeout=20)
for r4 in resp4.json()[:3]:
    print(f"  {r4.get('osm_type')}/{r4.get('osm_id')} class={r4.get('class')} type={r4.get('type')} bb={r4.get('boundingbox')} name={r4.get('display_name','')[:60]}")
