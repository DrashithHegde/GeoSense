import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.abspath("server"))
from app.services.surfaces.lst_surface import publish_lst_geotiff

temp_tif = Path("temp_new_lst.tif")
start_date = "2026-07-02"
end_date = "2026-08-16"
record = publish_lst_geotiff(temp_tif, start_date=start_date, end_date=end_date, image_count=0)
print(record)
