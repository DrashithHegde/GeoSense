import requests, json

# Overpass seems rate-limited. Use Nominatim lookup which returns tags too
NOMINATIM_LOOKUP = "https://nominatim.openstreetmap.org/lookup"

for label, osm_ids in [("Mumbai City District", "R7964376"), ("Mumbai Suburban District", "R7964375"),
                        ("Thane Subdistrict", "R7120000"), ("Mira-Bhayandar", "R13180677")]:
    resp = requests.get(NOMINATIM_LOOKUP,
        params={"osm_ids": osm_ids, "format": "json", "addressdetails": 1, "extratags": 1, "namedetails": 1},
        headers={"User-Agent": "GeoSense/1.0"}, timeout=20)
    results = resp.json()
    if not results:
        print(f"{label}: no result")
        continue
    r = results[0]
    print(f"\n{label} | {osm_ids}")
    print(f"  class/type: {r.get('class')}/{r.get('type')}")
    print(f"  display_name: {r.get('display_name','')[:100]}")
    xt = r.get("extratags", {})
    for k in ["admin_level", "wikipedia", "wikidata", "official_name", "population", "boundary"]:
        if k in xt:
            print(f"  extratag {k}: {xt[k]}")
    print(f"  boundingbox: {r.get('boundingbox')}")
