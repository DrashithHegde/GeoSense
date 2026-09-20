import requests
for q in ["Brihanmumbai", "Greater Mumbai"]:
    resp = requests.get('https://nominatim.openstreetmap.org/search', params={'q': q, 'format': 'json', 'limit': 5}, headers={'User-Agent': 'GeoSense/1.0'})
    print(f"\nResults for {q}:")
    for r in resp.json():
        print(f"  {r.get('osm_type')}/{r.get('osm_id')} : {r.get('class')}/{r.get('type')} - {r.get('display_name')}")
