import re
from pathlib import Path

path = Path("server/app/api/routes.py")
content = path.read_text(encoding="utf-8")

# 1. Add rasterio and numpy imports if not present
if "import rasterio" not in content:
    content = content.replace("from fastapi import APIRouter", "import rasterio\nimport numpy as np\nfrom fastapi import APIRouter")

# 2. Insert the pixel click endpoint
pixel_endpoint = """
@router.get("/surfaces/lst/value")
async def get_lst_pixel_value(lon: float, lat: float):
    \"\"\"Return pixel-level LST value from the underlying GeoTIFF.\"\"\"
    surface = load_latest_lst_surface()
    if not surface:
        raise HTTPException(status_code=404, detail="No LST surface available")
        
    tif_filename = surface["files"]["geotiff"]
    from pathlib import Path
    import os
    import numpy as np
    import rasterio
    
    SERVER_ROOT = Path(__file__).resolve().parents[3]
    tif_path = SERVER_ROOT / "data" / "surfaces" / "lst" / tif_filename
    
    if not tif_path.exists():
        raise HTTPException(status_code=404, detail="GeoTIFF not found")
        
    try:
        with rasterio.open(tif_path) as dataset:
            if not (dataset.bounds.left <= lon <= dataset.bounds.right and dataset.bounds.bottom <= lat <= dataset.bounds.top):
                return {
                    "metric": "lst", "longitude": lon, "latitude": lat,
                    "value_c": None, "nodata": True, "source": surface["methodology"],
                    "resolution_m": surface["scale_m"], "source_period": surface["source_period"]
                }
            
            row, col = dataset.index(lon, lat)
            val = dataset.read(1)[row, col]
            is_nodata = bool(val == dataset.nodata or not np.isfinite(val))
            
            return {
                "metric": "lst",
                "longitude": lon,
                "latitude": lat,
                "value_c": None if is_nodata else round(float(val), 2),
                "nodata": is_nodata,
                "source": "Landsat 8/9 Collection 2 Level-2 Surface Temperature",
                "resolution_m": surface["scale_m"],
                "source_period": surface["source_period"]
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
"""

if "/surfaces/lst/value" not in content:
    content = content.replace("return response\n\n\n@router.get(\"/zones/boundary\")", f"return response\n\n{pixel_endpoint}\n\n@router.get(\"/zones/boundary\")")

# 3. Update explanation endpoint to take pixel_lst
if "pixel_lst: Optional[float] = None" not in content:
    content = content.replace(
        "async def get_zone_explanation(zone_id: int, db_cm=Depends(get_db)):",
        "async def get_zone_explanation(zone_id: int, pixel_lst: Optional[float] = None, db_cm=Depends(get_db)):"
    )
    content = content.replace(
        "result = await build_full_explanation(db, zone_id)",
        "result = await build_full_explanation(db, zone_id, pixel_lst)"
    )

path.write_text(content, encoding="utf-8")
print("Patched routes.py")
