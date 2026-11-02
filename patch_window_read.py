import re
from pathlib import Path

path = Path("server/app/api/routes.py")
content = path.read_text(encoding="utf-8")

old_read = "val = dataset.read(1)[row, col]"
new_read = "from rasterio.windows import Window\n            val = dataset.read(1, window=Window(col, row, 1, 1))[0, 0]"
content = content.replace(old_read, new_read)

path.write_text(content, encoding="utf-8")
print("Fixed rasterio window read")
