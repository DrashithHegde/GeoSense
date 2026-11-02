import re
from pathlib import Path

path = Path("client/src/App.jsx")
content = path.read_text(encoding="utf-8")

old_zone_click = """  function handleZoneClick(zone) {
    setSelectedZone(zone);
    if (zone.id && !String(zone.id).startsWith("mum-") && !String(zone.id).startsWith("blr-") && !String(zone.id).startsWith("del-")) {
      // Real backend zone ID
      fetchExplanation(zone.id);
    } else {"""

new_zone_click = """  function handleZoneClick(zone) {
    setSelectedZone(zone);
    if (zone.id && !String(zone.id).startsWith("mum-") && !String(zone.id).startsWith("blr-") && !String(zone.id).startsWith("del-")) {
      // Real backend zone ID
      const pixelLst = zone.pixelLST && !zone.pixelLST.nodata ? zone.pixelLST.value_c : null;
      fetchExplanation(zone.id, pixelLst);
    } else {"""

content = content.replace(old_zone_click, new_zone_click)

path.write_text(content, encoding="utf-8")
print("Patched App.jsx")
