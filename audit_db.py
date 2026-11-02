import sys, pathlib, math
sys.path.insert(0, str(pathlib.Path(r'C:\Users\DRASHITH HEGDE\OneDrive\Desktop\GeoSense\server')))
import psycopg2

conn = psycopg2.connect('dbname=geosense user=postgres password=postgres host=localhost port=5433')
cur = conn.cursor()

cur.execute('SELECT count(*) FROM zones;')
print("zones:", cur.fetchone()[0])

cur.execute('SELECT count(*) FROM environment_data;')
print("environment_data:", cur.fetchone()[0])

cur.execute('SELECT count(*) FROM engineered_features;')
print("engineered_features:", cur.fetchone()[0])

cur.execute('SELECT count(*) FROM anomaly_results;')
print("anomaly_results:", cur.fetchone()[0])

# Newest AQI rows provenance
cur.execute("""
    SELECT aqi_source_type, source_metadata->'aqi'->>'method', count(*), max(observed_at)
    FROM environment_data
    WHERE aqi IS NOT NULL
    GROUP BY 1,2 ORDER BY max(observed_at) DESC LIMIT 10;
""")
print("\nAQI provenance groups:")
for row in cur.fetchall():
    print(" ", row)

# Check for any future timestamps
cur.execute("""
    SELECT count(*) FROM environment_data WHERE observed_at > NOW();
""")
print("\nFuture timestamps:", cur.fetchone()[0])

cur.close()
conn.close()
