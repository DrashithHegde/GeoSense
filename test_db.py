import os
import sys
sys.path.insert(0, os.path.abspath("server"))
from app.database import engine
from sqlalchemy import text

statement = text("""
    SELECT ST_XMin(extent) AS west, ST_YMin(extent) AS south,
           ST_XMax(extent) AS east, ST_YMax(extent) AS north
    FROM (SELECT ST_Extent(geometry)::box3d AS extent FROM zones) zone_extent
""")
with engine.connect() as connection:
    row = connection.execute(statement).mappings().one()
    print("DB Bounds:", row)
    
    west = float(row["west"]) - 0.08
    south = float(row["south"]) - 0.05
    east = float(row["east"]) + 0.03
    north = float(row["north"]) + 0.12
    print("Expanded Bounds:", (west, south, east, north))
