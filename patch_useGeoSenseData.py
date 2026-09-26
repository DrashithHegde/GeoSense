import re
from pathlib import Path

path = Path("client/src/hooks/useGeoSenseData.js")
content = path.read_text(encoding="utf-8")

if "pixelLst" not in content:
    content = content.replace(
        "const fetchExplanation = useCallback(async (zoneId) => {",
        "const fetchExplanation = useCallback(async (zoneId, pixelLst = null) => {"
    )
    content = content.replace(
        "const url = getApiUrl(`/api/zones/${zoneId}/explanation`);",
        "let url = getApiUrl(`/api/zones/${zoneId}/explanation`);\n      if (pixelLst !== null) url += `?pixel_lst=${pixelLst}`;"
    )

path.write_text(content, encoding="utf-8")
print("Patched useGeoSenseData.js")
