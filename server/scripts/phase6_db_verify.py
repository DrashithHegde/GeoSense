"""Phase 6 live database verification script. READ-ONLY queries."""
import sys
from pathlib import Path

# ensure imports resolve
REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = REPO_ROOT / "server"
for p in (str(REPO_ROOT), str(SERVER_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.database import engine
from sqlalchemy import text


def run():
    with engine.connect() as conn:
        # A) Raw row count, distinct keys, duplicates
        r = conn.execute(text("""
            SELECT
                count(*) AS total_rows,
                count(DISTINCT (zone_id, observed_at)) AS distinct_zone_timestamps,
                count(*) - count(DISTINCT (zone_id, observed_at)) AS duplicates,
                count(*) FILTER (WHERE source_metadata != cast('{}' as jsonb)) AS provenance_bearing_rows,
                min(observed_at) AS earliest,
                max(observed_at) AS latest
            FROM environment_data
        """)).mappings().one()
        print("=== RAW TABLE ===")
        for k, v in r.items():
            print(f"  {k}: {v}")

        # B) Per-metric non-null counts
        print()
        print("=== PER-METRIC NON-NULL COUNTS ===")
        r2 = conn.execute(text("""
            SELECT
                count(*) FILTER (WHERE aqi IS NOT NULL) AS aqi_rows,
                count(*) FILTER (WHERE lst IS NOT NULL) AS lst_rows,
                count(*) FILTER (WHERE ndvi IS NOT NULL) AS ndvi_rows,
                count(*) FILTER (WHERE ndwi IS NOT NULL) AS ndwi_rows,
                count(*) FILTER (WHERE lst IS NULL) AS lst_null_rows
            FROM environment_data
        """)).mappings().one()
        for k, v in r2.items():
            print(f"  {k}: {v}")

        # C) Latest timestamps per metric
        print()
        print("=== LATEST TIMESTAMPS PER METRIC ===")
        r3 = conn.execute(text("""
            SELECT
                max(observed_at) FILTER (WHERE aqi IS NOT NULL) AS latest_aqi,
                max(observed_at) FILTER (WHERE lst IS NOT NULL) AS latest_lst,
                max(observed_at) FILTER (WHERE ndvi IS NOT NULL) AS latest_ndvi,
                max(observed_at) FILTER (WHERE ndwi IS NOT NULL) AS latest_ndwi
            FROM environment_data
        """)).mappings().one()
        for k, v in r3.items():
            print(f"  {k}: {v}")

        # D) AQI latest snapshot breakdown
        print()
        print("=== LATEST AQI SNAPSHOT ===")
        r4 = conn.execute(text("""
            WITH latest AS (
                SELECT max(observed_at) AS ts FROM environment_data WHERE aqi IS NOT NULL
            )
            SELECT
                latest.ts,
                count(*) FILTER (WHERE e.aqi_source_type = 'observed') AS observed_zones,
                count(*) FILTER (WHERE e.aqi_source_type = 'estimated') AS estimated_zones,
                count(*) FILTER (WHERE e.aqi IS NULL) AS uncovered_zones,
                count(*) AS total_in_snapshot
            FROM latest
            LEFT JOIN environment_data e ON e.observed_at = latest.ts
            GROUP BY latest.ts
        """)).mappings().one()
        for k, v in r4.items():
            print(f"  {k}: {v}")

        # D2) AQI value range in latest snapshot
        print()
        print("=== LATEST AQI VALUE RANGE ===")
        r4b = conn.execute(text("""
            WITH latest AS (
                SELECT max(observed_at) AS ts FROM environment_data WHERE aqi IS NOT NULL
            )
            SELECT
                min(e.aqi) AS aqi_min,
                max(e.aqi) AS aqi_max,
                round(avg(e.aqi), 2) AS aqi_mean
            FROM latest
            JOIN environment_data e ON e.observed_at = latest.ts AND e.aqi IS NOT NULL
        """)).mappings().one()
        for k, v in r4b.items():
            print(f"  {k}: {v}")

        # E) NDVI/NDWI range in latest snapshot
        print()
        print("=== LATEST NDVI/NDWI RANGES ===")
        r5b = conn.execute(text("""
            WITH latest AS (
                SELECT max(observed_at) AS ts FROM environment_data WHERE ndvi IS NOT NULL
            )
            SELECT
                min(e.ndvi) AS ndvi_min, max(e.ndvi) AS ndvi_max,
                min(e.ndwi) AS ndwi_min, max(e.ndwi) AS ndwi_max,
                count(*) FILTER (WHERE e.ndvi IS NOT NULL) AS ndvi_count,
                count(*) FILTER (WHERE e.ndwi IS NOT NULL) AS ndwi_count
            FROM latest
            JOIN environment_data e ON e.observed_at = latest.ts
        """)).mappings().one()
        for k, v in r5b.items():
            print(f"  {k}: {v}")

        # F) Anomaly results
        print()
        print("=== ANOMALY RESULTS ===")
        r5 = conn.execute(text("""
            SELECT
                count(*) AS total_results,
                count(*) FILTER (WHERE is_anomaly) AS anomaly_count,
                count(*) FILTER (WHERE NOT is_anomaly) AS inlier_count,
                count(DISTINCT observed_at) AS distinct_snapshots,
                max(observed_at) AS latest_snapshot,
                round(cast(min(anomaly_score) as numeric), 6) AS min_score,
                round(cast(max(anomaly_score) as numeric), 6) AS max_score
            FROM anomaly_results
            WHERE model_name = 'isolation_forest_spatial_v1'
        """)).mappings().one()
        for k, v in r5.items():
            print(f"  {k}: {v}")

        # G) Engineered features
        print()
        print("=== ENGINEERED FEATURES ===")
        r6 = conn.execute(text("""
            SELECT
                count(*) AS total_feature_rows,
                count(DISTINCT observed_at) AS distinct_snapshots,
                max(observed_at) AS latest_snapshot
            FROM engineered_features
        """)).mappings().one()
        for k, v in r6.items():
            print(f"  {k}: {v}")

        # H) Legacy checksum (first 385 rows by id)
        print()
        print("=== LEGACY CHECKSUM (first 385 rows) ===")
        r7 = conn.execute(text("""
            SELECT md5(string_agg(concat(zone_id,'|',observed_at::text,'|',coalesce(aqi::text,'NULL')), ',' ORDER BY id))
            FROM (SELECT id, zone_id, observed_at, aqi FROM environment_data ORDER BY id LIMIT 385) sub
        """)).scalar()
        print(f"  checksum: {r7}")
        expected_legacy = "23bc56d26b08d2f92e63a0731b2288fc"
        print(f"  expected: {expected_legacy}")
        print(f"  match:    {r7 == expected_legacy}")

        # I) Current full checksum
        print()
        print("=== CURRENT FULL CHECKSUM ===")
        r8 = conn.execute(text("""
            SELECT md5(string_agg(concat(zone_id,'|',observed_at::text,'|',coalesce(aqi::text,'NULL')), ',' ORDER BY id))
            FROM environment_data
        """)).scalar()
        print(f"  checksum: {r8}")

        # J) Temporal readiness: distinct prior obs per metric
        print()
        print("=== TEMPORAL READINESS (prior obs per metric) ===")
        for metric in ("aqi", "lst", "ndvi", "ndwi"):
            rc = conn.execute(text(f"""
                SELECT count(DISTINCT observed_at) AS distinct_timestamps
                FROM environment_data
                WHERE {metric} IS NOT NULL
            """)).scalar()
            print(f"  {metric}: {rc} distinct timestamps")

        # K) Provenance spot-check: sample latest sentinel-2 metadata
        print()
        print("=== SENTINEL-2 PROVENANCE SPOT-CHECK (1 zone) ===")
        rprov = conn.execute(text("""
            SELECT zone_id, observed_at, source_metadata->'ndvi_ndwi' AS ndvi_ndwi_meta
            FROM environment_data
            WHERE ndvi IS NOT NULL
            ORDER BY observed_at DESC, zone_id ASC
            LIMIT 1
        """)).mappings().one()
        print(f"  zone_id: {rprov['zone_id']}")
        print(f"  observed_at: {rprov['observed_at']}")
        print(f"  ndvi_ndwi_meta: {rprov['ndvi_ndwi_meta']}")

        # L) LST null check on latest window
        print()
        print("=== LATEST LST ROW SAMPLE (checking nulls) ===")
        rlst = conn.execute(text("""
            SELECT zone_id, observed_at, lst, source_metadata->'lst' AS lst_meta
            FROM environment_data
            ORDER BY observed_at DESC, zone_id ASC
            LIMIT 5
        """)).mappings().all()
        for row in rlst:
            print(f"  zone={row['zone_id']} observed_at={row['observed_at']} lst={row['lst']} meta={row['lst_meta']}")

    print()
    print("DB VERIFICATION COMPLETE")


if __name__ == "__main__":
    run()
