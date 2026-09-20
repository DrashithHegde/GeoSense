import geopandas as gpd
from sqlalchemy import create_engine
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

def load_localities_to_db():
    # Connect to PostgreSQL
    db_user = os.getenv('DB_USER', 'postgres')
    db_pass = os.getenv('DB_PASSWORD', 'postgres')
    db_host = os.getenv('DB_HOST', 'localhost')
    db_name = os.getenv('DB_NAME', 'geosense')
    
    engine = create_engine(f"postgresql://{db_user}:{db_pass}@{db_host}/{db_name}")

    if not os.path.exists('mumbai_village_boundaries.geojson'):
        print("Please download 'mumbai_village_boundaries.geojson' before running this.")
        return

    # Load to database
    gdf = gpd.read_file('mumbai_village_boundaries.geojson')
    gdf.to_postgis('localities', engine, if_exists='replace', index=False)
    print(f"✅ Loaded {len(gdf)} localities to database")

if __name__ == "__main__":
    load_localities_to_db()
