import re
from pathlib import Path

path = Path("server/app/services/surfaces/lst_surface.py")
content = path.read_text(encoding="utf-8")

old_profile = """        transform = source.transform
        bounds = source.bounds
        profile = source.profile.copy()"""

new_profile = """        transform = source.transform
        bounds = source.bounds
        profile = source.profile.copy()
        profile["nodata"] = NODATA_VALUE"""

content = content.replace(old_profile, new_profile)

path.write_text(content, encoding="utf-8")
print("Patched publish_lst_geotiff profile nodata")
