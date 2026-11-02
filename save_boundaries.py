import requests, json
from shapely.geometry import shape, mapping
from shapely.ops import unary_union
import pathlib

nom_lookup = "https://nominatim.openstreetmap.org/lookup"

relations = {
    "mumbai_city": "R7964376",
    "mumbai_suburban": "R7964375",
    "thane": "R7120000",
    "mira_bhayandar": "R13180677",
}

geoms = {}
for slug, osm_id in relations.items():
    resp = requests.get(nom_lookup,
        params={"osm_ids": osm_id, "format": "json", "polygon_geojson": 1},
        headers={"User-Agent": "GeoSense/1.0"}, timeout=30)
    results = resp.json()
    r = results[0]
    geoms[slug] = shape(r["geojson"])

# Combine Mumbai City + Suburban = BMC
mumbai_combined = unary_union([geoms["mumbai_city"], geoms["mumbai_suburban"]])

# Prepare output directory
out_dir = pathlib.Path(r"C:\Users\DRASHITH HEGDE\OneDrive\Desktop\GeoSense\server\data\boundaries")
out_dir.mkdir(parents=True, exist_ok=True)

def write_geojson(path, geom, props):
    fc = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": props,
            "geometry": mapping(geom)
        }]
    }
    path.write_text(json.dumps(fc, indent=2), encoding="utf-8")
    print(f"Written: {path} ({path.stat().st_size} bytes)")

write_geojson(out_dir / "mumbai.geojson", mumbai_combined, {
    "id": "mumbai", "name": "Mumbai",
    "osm_relations": ["R7964376 (Mumbai City District)", "R7964375 (Mumbai Suburban District)"],
    "source": "OpenStreetMap via Nominatim lookup",
    "note": "Union of Mumbai City District and Mumbai Suburban District = BMC jurisdiction"
})

write_geojson(out_dir / "thane.geojson", geoms["thane"], {
    "id": "thane", "name": "Thane",
    "osm_relations": ["R7120000 (Thane Subdistrict)"],
    "source": "OpenStreetMap via Nominatim lookup",
    "note": "Thane Subdistrict admin boundary - 141 km2 approximating Thane MC (actual 147 km2)"
})

write_geojson(out_dir / "mira_bhayandar.geojson", geoms["mira_bhayandar"], {
    "id": "mira_bhayandar", "name": "Mira-Bhayandar",
    "osm_relations": ["R13180677 (Mira-Bhayander)"],
    "source": "OpenStreetMap via Nominatim lookup",
    "note": "Mira-Bhayandar administrative boundary - 89 km2 approximating MBMC (actual 79 km2)"
})

print("Done. Files created in server/data/boundaries/")
