import requests, json

# Verify via Wikipedia/Wikidata what each entity actually is
# Q2341660 = Mumbai City district - Wikipedia: district
# Q2085374 = Mumbai Suburban district - Wikipedia: district
# Q207749 = Thane - wikidata - let us check
# Q1006343 = Mira-Bhayandar - wikidata - let us check

# Check OSM for a direct "Brihanmumbai Municipal Corporation" boundary relation
# Search Nominatim for municipal corporations specifically
NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search"

searches = [
    "Brihanmumbai Municipal Corporation boundary",
    "BMC Mumbai municipal corporation",
    "Greater Mumbai municipal",
    "Thane Municipal Corporation",
    "Thane Mahanagar Palika",
    "Mira Bhayandar Municipal Corporation",
]

print("=== SEARCHING FOR DIRECT MUNICIPAL CORPORATION BOUNDARIES ===")
for q in searches:
    resp = requests.get(NOMINATIM_SEARCH,
        params={"q": q, "format": "json", "limit": 3, "countrycodes": "in"},
        headers={"User-Agent": "GeoSense/1.0"}, timeout=20)
    results = resp.json()
    if results:
        for r in results[:2]:
            print(f"  '{q[:40]}' -> {r.get('osm_type')}/{r.get('osm_id')} class={r.get('class')}/{r.get('type')} name={r.get('display_name','')[:80]}")
    else:
        print(f"  '{q[:40]}' -> NO RESULTS")
