import re
from pathlib import Path

path = Path("client/src/hooks/index.js")
content = path.read_text(encoding="utf-8")

# Fix line 711 missing lstSurfaceRef.current
content = content.replace(
    "applyMunicipalityPaint(map, activeLayers, selectedMuniRef.current, !!aqiSurfaceRef.current, !!ndviSurfaceRef.current);",
    "applyMunicipalityPaint(map, activeLayers, selectedMuniRef.current, !!aqiSurfaceRef.current, !!ndviSurfaceRef.current, !!lstSurfaceRef.current);"
)

# Modify handleMuniClick to fetch pixel data in LST mode
old_muni_click = """      selectedMuniRef.current = muniId;
      applyMunicipalityPaint(map, activeLayersRef.current, muniId, !!aqiSurfaceRef.current, !!ndviSurfaceRef.current, !!lstSurfaceRef.current);
      onZoneClickRef.current?.(zone);
      map.stop();
      map.easeTo({ center: [e.lngLat.lng, e.lngLat.lat], zoom: Math.max(map.getZoom(), 10.5), pitch: 52, bearing: -10, duration: 1100, essential: true });"""

new_muni_click = """      selectedMuniRef.current = muniId;
      applyMunicipalityPaint(map, activeLayersRef.current, muniId, !!aqiSurfaceRef.current, !!ndviSurfaceRef.current, !!lstSurfaceRef.current);
      
      const layerId = getPrimaryLayerId(activeLayersRef.current);
      if (layerId === 'lst') {
         fetch(getApiUrl(`/api/surfaces/lst/value?lon=${e.lngLat.lng}&lat=${e.lngLat.lat}`))
           .then(r => r.json())
           .then(pixelData => {
              zone.pixelLST = pixelData;
              onZoneClickRef.current?.(zone);
           })
           .catch(err => {
              console.error("LST pixel fetch failed", err);
              onZoneClickRef.current?.(zone);
           });
      } else {
         onZoneClickRef.current?.(zone);
      }
      
      map.stop();
      map.easeTo({ center: [e.lngLat.lng, e.lngLat.lat], zoom: Math.max(map.getZoom(), 10.5), pitch: 52, bearing: -10, duration: 1100, essential: true });"""
      
content = content.replace(old_muni_click, new_muni_click)

# Modify applyMunicipalityPaint FLIR mode for MUNI_EXTRUDE
old_extrude = """  if (map.getLayer(MUNI_EXTRUDE)) {
    // FLIR mode: hide municipality fills completely — only thermal surface should be visible
    if (isFLIRMode) {
      map.setLayoutProperty(MUNI_EXTRUDE, "visibility", "none");
    } else {"""
    
new_extrude = """  if (map.getLayer(MUNI_EXTRUDE)) {
    // FLIR mode: hide municipality fills visually but keep them clickable
    if (isFLIRMode) {
      map.setLayoutProperty(MUNI_EXTRUDE, "visibility", "visible");
      map.setPaintProperty(MUNI_EXTRUDE, "fill-extrusion-opacity", 0.0);
    } else {"""
    
content = content.replace(old_extrude, new_extrude)

path.write_text(content, encoding="utf-8")
print("Patched hooks/index.js")
