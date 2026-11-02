import re
with open('app/api/routes.py', 'r') as f:
    text = f.read()

# I will use Python to replace the get_latest_metrics function
import ast
import textwrap

new_func = \"\"\"
@router.get("/metrics/latest")
async def get_latest_metrics(db_cm=Depends(get_db)):
    with db_cm as db:
        zones = db.execute(
            select(
                Zone.id.label("id"),
                Zone.name.label("name"),
                Zone.ward.label("ward"),
                func.ST_X(func.ST_Centroid(Zone.geometry)).label("longitude"),
                func.ST_Y(func.ST_Centroid(Zone.geometry)).label("latitude")
            )
        ).mappings().all()
        
        gee_rows = db.execute(
            select(
                EnvironmentData.zone_id,
                EnvironmentData.ndvi,
                EnvironmentData.ndwi,
                EnvironmentData.lst,
                EnvironmentData.observed_at
            )
            .where(EnvironmentData.ndvi.isnot(None))
            .distinct(EnvironmentData.zone_id)
            .order_by(EnvironmentData.zone_id, EnvironmentData.observed_at.desc())
        ).mappings().all()
        gee_dict = {r["zone_id"]: dict(r) for r in gee_rows}

        aqi_rows = db.execute(
            select(
                EnvironmentData.zone_id,
                EnvironmentData.aqi,
                EnvironmentData.pm25,
                EnvironmentData.pm10,
                EnvironmentData.no2,
                EnvironmentData.observed_at,
                EnvironmentData.aqi_source_type,
                EnvironmentData.aqi_nearest_station_distance_m
            )
            .where(EnvironmentData.aqi.isnot(None))
            .distinct(EnvironmentData.zone_id)
            .order_by(EnvironmentData.zone_id, EnvironmentData.observed_at.desc())
        ).mappings().all()
        aqi_dict = {r["zone_id"]: dict(r) for r in aqi_rows}

        out = []
        for z in zones:
            zid = z["id"]
            d = dict(z)
            gd = gee_dict.get(zid, {})
            ad = aqi_dict.get(zid, {})
            
            d["ndvi"] = gd.get("ndvi")
            d["ndwi"] = gd.get("ndwi")
            d["lst"] = gd.get("lst")
            
            d["aqi"] = ad.get("aqi")
            d["pm25"] = ad.get("pm25")
            d["pm10"] = ad.get("pm10")
            d["no2"] = ad.get("no2")
            
            date1 = ad.get("observed_at")
            date2 = gd.get("observed_at")
            d["date"] = date1 if date1 else date2
            
            d["aqi_source_type"] = ad.get("aqi_source_type")
            d["aqi_nearest_station_distance_m"] = ad.get("aqi_nearest_station_distance_m")
            d["temperature"] = None
            d["humidity"] = None
            out.append(d)
        return out
\"\"\"

# regex substitution
pattern = re.compile(r'@router\.get\("/metrics/latest"\).*?return out\n', re.DOTALL)
new_text = pattern.sub(new_func, text)
with open('app/api/routes.py', 'w') as f:
    f.write(new_text)

