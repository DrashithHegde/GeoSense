# Other cities' data

One folder per city with the same layout as Mumbai's (`server/data/`):

```text
<city>/boundaries/<city>.geojson   in git — built by scripts/import_city_boundaries.py (DataMeet, CC BY-SA 2.5 IN)
<city>/surfaces/                    map layers (scripts/setup_city.py) — not in git, shipped in the data bundle
<city>/ml/                          ML summary and models
<city>/history/                     seasonal history summaries
```
