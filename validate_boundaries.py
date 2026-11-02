import requests, json
from shapely.geometry import shape
from shapely.ops import unary_union

nom_lookup = "https://nominatim.openstreetmap.org/lookup"

def get_area_km2(geom):
    return geom.area * 11655

# Fetch all four key relations with full polygon geometries
relations = {
    "Mumbai City District": "R7964376",
    "Mumbai Suburban District": "R7964375",
    "Thane Subdistrict (TMC proxy)": "R7120000",
    "Mira-Bhayander": "R13180677",
}

geoms = {}
for label, osm_id in relations.items():
    resp = requests.get(nom_lookup,
        params={"osm_ids": osm_id, "format": "json", "polygon_geojson": 1},
        headers={"User-Agent": "GeoSense/1.0"}, timeout=30)
    results = resp.json()
    if not results:
        print(f"NOT FOUND: {label}")
        continue
    r = results[0]
    geom = shape(r["geojson"])
    area = get_area_km2(geom)
    bounds = tuple(round(b, 5) for b in geom.bounds)
    print(f"\n{label} | {osm_id}")
    print(f"  area = {area:.1f} km2")
    print(f"  bounds = {bounds}")
    print(f"  geom_type = {geom.geom_type}")
    geoms[label] = geom

# Check if Mumbai districts overlap (they should not for BMC)
if "Mumbai City District" in geoms and "Mumbai Suburban District" in geoms:
    overlap = geoms["Mumbai City District"].intersection(geoms["Mumbai Suburban District"])
    print(f"\nMumbai City + Suburban overlap area = {get_area_km2(overlap):.1f} km2 (should be ~0)")
    combined = unary_union([geoms["Mumbai City District"], geoms["Mumbai Suburban District"]])
    print(f"Combined Mumbai (BMC) area = {get_area_km2(combined):.1f} km2 (expected ~437 km2)")
    cb = tuple(round(b,5) for b in combined.bounds)
    print(f"Combined bounds = {cb}")

# Check Thane vs Mira-Bhayandar overlap (should be minimal or zero)
if "Thane Subdistrict (TMC proxy)" in geoms and "Mira-Bhayander" in geoms:
    overlap2 = geoms["Thane Subdistrict (TMC proxy)"].intersection(geoms["Mira-Bhayander"])
    print(f"\nThane vs MB overlap area = {get_area_km2(overlap2):.1f} km2 (should be ~0)")
