import re
from pathlib import Path

path = Path("server/app/services/surfaces/lst_surface.py")
content = path.read_text(encoding="utf-8")

old_expansion = """    # Expand bounds to include Sanjay Gandhi National Park and surrounding natural areas
    west = float(row["west"]) - 0.08   # ~8km west expansion
    south = float(row["south"]) - 0.05  # ~5km south expansion
    east = float(row["east"]) + 0.03    # ~3km east expansion
    north = float(row["north"]) + 0.12  # ~12km north expansion (captures national park)"""

new_expansion = """    # Expand bounds to include Sanjay Gandhi National Park and surrounding municipalities (Mira-Bhayandar, Thane)
    west = float(row["west"]) - 0.08   # ~8km west expansion
    south = float(row["south"]) - 0.05  # ~5km south expansion
    east = float(row["east"]) + 0.15    # ~15km east expansion (captures Thane)
    north = float(row["north"]) + 0.15  # ~15km north expansion (captures Mira-Bhayandar)"""

content = content.replace(old_expansion, new_expansion)

path.write_text(content, encoding="utf-8")
print("Patched get_lst_export_bounds")
