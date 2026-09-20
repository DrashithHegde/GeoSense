import re

with open('app/api/routes.py', 'r') as f:
    text = f.read()

# Add ST_AsGeoJSON
text = text.replace(
    'ST_Y(ST_Centroid(z.geometry)) AS latitude,',
    'ST_Y(ST_Centroid(z.geometry)) AS latitude,\n                ST_AsGeoJSON(z.geometry) AS geometry_geojson,'
)

# Parse it into the dictionary
text = text.replace(
    'd["composite"] = calculate_composite(',
    'd["geometry"] = json.loads(d.pop("geometry_geojson")) if d.get("geometry_geojson") else None\n            d["composite"] = calculate_composite('
)

with open('app/api/routes.py', 'w') as f:
    f.write(text)
