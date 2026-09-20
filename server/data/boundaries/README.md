# GeoSense municipality context boundaries

`mumbai.geojson`, `thane.geojson`, and `mira_bhayandar.geojson` are local,
WGS84 GeoJSON assets used by the municipality-summary API for geometry/context.
They are deliberately loaded locally: serving the API must never issue a
free-text Nominatim request or silently substitute another boundary.

These files are **candidate placeholders**, not verified authoritative municipal
jurisdiction boundaries and must not yet be used as final hard environmental
clipping masks. The boundary verification audit identified direct-source
differences for all three municipalities. Any replacement must retain the same
filename and `properties.id`, be a valid Polygon/MultiPolygon in EPSG:4326, and
include documented direct municipal-source provenance.

The 189 GeoSense analytical zones are independent frozen backend geometry and
are never created, modified, or removed by this boundary asset mechanism.
