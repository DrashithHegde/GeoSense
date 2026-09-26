import pathlib
import re

path = pathlib.Path("gee/ingest_ndvi_ndwi.py")
text = path.read_text(encoding="utf-8")

# Fix zone_id residues
text = text.replace('props.get("zone_id")', 'props.get("cell_id")')
text = text.replace('feature.get("properties", {}).get("zone_id")', 'feature.get("properties", {}).get("cell_id")')
text = text.replace('feature["properties"].get("zone_id")', 'feature["properties"].get("cell_id")')
text = text.replace('water_extent_lookup.get(zone_id)', 'water_extent_lookup.get(cell_id)')

# Implement chunking
text = text.replace('''        cells_fc = fetch_cells_as_feature_collection(db)

        # Filter S2 harmonized
        collection = (
            ee.ImageCollection(S2_DATASET)
            .filterDate(start_date, end_date)
            .filterBounds(cells_fc.geometry())
        )

        n_images = int(collection.size().getInfo())
        logger.info("Images found in window: %s", n_images)

        if n_images == 0:
            logger.warning("No Sentinel-2 images found in the given window.")

        # Apply QA mask and compute indices per image
        collection = collection.map(mask_s2_sr).map(add_indices)

        # Median composite
        composite = collection.median().select(["NDVI", "NDWI", "MNDWI", "NDCI_PROXY", "TURBIDITY_PROXY"])

        # Reduce over the feature collection (zones)
        reducer = ee.Reducer.mean()
        reduced = composite.reduceRegions(collection=cells_fc, reducer=reducer, scale=10)

        water_extent_reduced = (
            ee.Image.pixelArea()
            .updateMask(composite.select("MNDWI").gte(DEFAULT_MNDWI_THRESHOLD))
            .reduceRegions(collection=cells_fc, reducer=ee.Reducer.sum(), scale=10)
        )

        water_extent_lookup = {
            int(feature["properties"].get("cell_id")): float(feature["properties"].get("sum", 0.0))
            for feature in water_extent_reduced.getInfo().get("features", [])
            if feature.get("properties", {}).get("cell_id") is not None
        }

        # Get results
        features = reduced.getInfo().get("features", [])''',
'''        # Create list of ee.Feature directly so we can chunk
        sql = text("SELECT id, ST_AsGeoJSON(geometry) AS geojson FROM spatial_cells;")
        result = db.execute(sql)
        all_ee_features = []
        import json
        for row in result:
            geom = json.loads(row[1])
            props = {"cell_id": int(row[0])}
            all_ee_features.append(ee.Feature(geom, props))

        # Filter S2 harmonized on overall bounding box
        overall_fc = ee.FeatureCollection(all_ee_features)
        collection = (
            ee.ImageCollection(S2_DATASET)
            .filterDate(start_date, end_date)
            .filterBounds(overall_fc.geometry())
        )

        n_images = int(collection.size().getInfo())
        logger.info("Images found in window: %s", n_images)
        if n_images == 0:
            logger.warning("No Sentinel-2 images found in the given window.")

        collection = collection.map(mask_s2_sr).map(add_indices)
        composite = collection.median().select(["NDVI", "NDWI", "MNDWI", "NDCI_PROXY", "TURBIDITY_PROXY"])
        reducer = ee.Reducer.mean()

        CHUNK_SIZE = 2500
        water_features = []
        features = []
        logger.info(f"Reducing {len(all_ee_features)} cells in chunks of {CHUNK_SIZE}...")
        for i in range(0, len(all_ee_features), CHUNK_SIZE):
            chunk = all_ee_features[i:i + CHUNK_SIZE]
            fc_chunk = ee.FeatureCollection(chunk)
            
            water_extent_reduced = (
                ee.Image.pixelArea()
                .updateMask(composite.select("MNDWI").gte(DEFAULT_MNDWI_THRESHOLD))
                .reduceRegions(collection=fc_chunk, reducer=ee.Reducer.sum(), scale=10)
            )
            water_features.extend(water_extent_reduced.getInfo().get("features", []))

            reduced = composite.reduceRegions(collection=fc_chunk, reducer=reducer, scale=10)
            features.extend(reduced.getInfo().get("features", []))

        water_extent_lookup = {
            int(feature["properties"].get("cell_id")): float(feature["properties"].get("sum", 0.0))
            for feature in water_features
            if feature.get("properties", {}).get("cell_id") is not None
        }''')

# Ensure we remove the variable `zone_id` completely
text = text.replace('zone_id = props.get("cell_id")', 'cell_id = props.get("cell_id")')

path.write_text(text, encoding="utf-8")
print("gee/ingest_ndvi_ndwi.py patched")
