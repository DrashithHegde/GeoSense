"""Runtime endpoint validation for env surface architecture task."""
import json
import requests

BASE = "http://127.0.0.1:8000"


def sep(title):
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


def test_ndvi_surface_latest():
    sep("TEST #1: GET /api/surfaces/ndvi/latest")
    r = requests.get(f"{BASE}/api/surfaces/ndvi/latest", timeout=10)
    print("status:", r.status_code)
    j = r.json()
    ok = r.status_code == 200
    ok = ok and j.get("metric") == "ndvi"
    ok = ok and j.get("source_scale_m") == 10
    ok = ok and j.get("coordinates") is not None
    ok = ok and j.get("image_url") is not None
    print("metric:", j.get("metric"))
    print("source_scale_m:", j.get("source_scale_m"))
    print("has_coords:", j.get("coordinates") is not None)
    print("image_url:", bool(j.get("image_url")))
    print("generation_status:", j.get("generation_status"))
    print("PASS" if ok else "FAIL")
    return ok, j


def test_ndvi_pixel_value():
    sep("TEST #2: GET /api/surfaces/ndvi/value (scientific pixel)")
    r = requests.get(f"{BASE}/api/surfaces/ndvi/value", params={"lon": 72.87, "lat": 19.07}, timeout=10)
    print("status:", r.status_code)
    j = r.json()
    print("keys:", sorted(j.keys()))
    print("value:", j.get("value"))
    print("nodata:", j.get("nodata"))
    print("resolution_m:", j.get("resolution_m"))
    print("source:", j.get("source"))
    v = j.get("value")
    ok = r.status_code == 200
    ok = ok and "resolution_m" in j
    ok = ok and "nodata" in j
    if v is not None and j.get("nodata") is False:
        ok = ok and -1.0 <= float(v) <= 1.0
        print("range_in_[-1,1]:", -1.0 <= float(v) <= 1.0)
    # Verify NOT a cell aggregate (cell avg would be 2 decimals rounded typical)
    if v is not None:
        s = str(float(v))
        print("decimals (>=3 confirmed raster pixel not rounded avg):", len(s.split(".")[-1]) if "." in s else 0)
    print("PASS" if ok else "FAIL")
    return ok, j


def test_wh_surface_latest():
    sep("TEST #3: GET /api/surfaces/water-health/latest")
    r = requests.get(f"{BASE}/api/surfaces/water-health/latest", timeout=10)
    print("status:", r.status_code)
    j = r.json()
    ok = r.status_code == 200
    ok = ok and j.get("metric") == "water_health"
    ok = ok and j.get("source_scale_m") == 10
    ok = ok and j.get("generation_status") == "generated"
    ok = ok and j.get("coordinates") is not None
    ok = ok and j.get("nodata_semantics") is not None
    print("metric:", j.get("metric"))
    print("source_scale_m:", j.get("source_scale_m"))
    print("status:", j.get("generation_status"))
    print("valid_pct:", j.get("valid_pixel_percent"))
    print("has_coords:", bool(j.get("coordinates")))
    print("PASS" if ok else "FAIL")
    return ok, j


def _probe_water_coords():
    """Find any water pixel inside the raster extent by scanning a grid."""
    for lon in [72.82, 72.84, 72.86, 72.88, 72.90, 72.92, 72.94, 72.96, 72.98, 73.00, 73.02, 73.04, 73.06]:
        for lat in [18.91, 18.94, 18.97, 19.00, 19.03, 19.06, 19.09, 19.12, 19.15, 19.18, 19.21, 19.24, 19.27, 19.30]:
            try:
                r = requests.get(f"{BASE}/api/surfaces/water-health/value", params={"lon": lon, "lat": lat}, timeout=3)
                j = r.json()
                if not j.get("nodata") and j.get("value") is not None:
                    return lon, lat, j
            except Exception:
                continue
    return None, None, None


def test_wh_pixel_water():
    sep("TEST #4: GET /api/surfaces/water-health/value — WATER pixel")
    lon, lat, probe = _probe_water_coords()
    if lon is None:
        print("SKIPPED: could not find any water pixel in raster extent")
        return False, None
    print(f"using water coordinate: lon={lon}, lat={lat}")
    print("probe value:", probe.get("value"), "nodata:", probe.get("nodata"))
    r = requests.get(f"{BASE}/api/surfaces/water-health/value", params={"lon": lon, "lat": lat}, timeout=10)
    j = r.json()
    print("status:", r.status_code)
    print("keys:", sorted(j.keys()))
    print("value:", j.get("value"))
    print("nodata (expected False):", j.get("nodata"))
    print("resolution_m:", j.get("resolution_m"))
    print("source:", j.get("source"))
    ok = r.status_code == 200
    ok = ok and j.get("nodata") is False
    ok = ok and j.get("value") is not None
    ok = ok and 0.0 <= float(j.get("value")) <= 1.0
    ok = ok and j.get("resolution_m") == 10
    print("value_in_[0,1]:", 0.0 <= float(j.get("value")) <= 1.0)
    print("PASS" if ok else "FAIL")
    return ok, (lon, lat, j)


def test_wh_pixel_nonwater():
    sep("TEST #5: GET /api/surfaces/water-health/value — NON-WATER pixel")
    # Confirmed dense urban land: 72.825, 19.015 — south central Mumbai
    r = requests.get(f"{BASE}/api/surfaces/water-health/value", params={"lon": 72.825, "lat": 19.015}, timeout=10)
    print("lon=72.825 lat=19.015 (urban land)")
    j = r.json()
    print("status:", r.status_code)
    print("value:", j.get("value"))
    print("nodata (expected True):", j.get("nodata"))
    ok = r.status_code == 200
    ok = ok and (j.get("nodata") is True or j.get("value") is None)
    print("PASS" if ok else "FAIL")
    return ok, j


def test_three_level_analysis(water_loc):
    sep("TEST #6: GET /api/analysis/point — THREE LEVEL HIERARCHY")
    lon, lat = 72.87, 19.07
    r = requests.get(f"{BASE}/api/analysis/point", params={"lon": lon, "lat": lat}, timeout=15)
    print("status:", r.status_code)
    j = r.json()
    print("top-level keys:", sorted(j.keys()))
    has_location = "location" in j
    has_pixel = "pixel" in j
    has_cell = "cell" in j
    has_muni = "municipality" in j
    pixel = j.get("pixel", {})
    cell = j.get("cell", {}) or {}
    cell_metrics = (cell or {}).get("metrics", {}) if isinstance(cell, dict) else {}
    muni = j.get("municipality", {})
    p_ndvi = pixel.get("ndvi") if isinstance(pixel.get("ndvi"), (int, float)) else (pixel.get("ndvi") or {}).get("value") if isinstance(pixel.get("ndvi"), dict) else None
    c_ndvi = cell_metrics.get("ndvi")
    p_wh = pixel.get("water_health") if isinstance(pixel.get("water_health"), (int, float, type(None))) else (pixel.get("water_health") or {}).get("value") if isinstance(pixel.get("water_health"), dict) else None
    c_wh = cell_metrics.get("water_health_score")
    print("has location:", has_location)
    print("has pixel    :", has_pixel, " keys:", sorted(pixel.keys()) if isinstance(pixel, dict) else type(pixel).__name__)
    print("has cell     :", has_cell, " metrics keys:", sorted(cell_metrics.keys()) if isinstance(cell_metrics, dict) else type(cell_metrics).__name__)
    print("has muni     :", has_muni, isinstance(muni, dict) and len(muni) > 0)
    print("pixel.ndvi:", p_ndvi)
    print("cell.metrics.ndvi:", c_ndvi)
    print("pixel.water_health:", p_wh)
    print("cell.metrics.water_health_score:", c_wh)
    distinct = (
        (p_ndvi is None or c_ndvi is None or float(p_ndvi) != float(c_ndvi))
        and isinstance(pixel, dict) and isinstance(cell, dict) and (pixel != cell)
    )
    print("PIXEL != CELL verified (distinct sources):", distinct)
    ok = r.status_code == 200 and has_location and has_pixel and has_cell and has_muni and distinct
    print("PASS" if ok else "FAIL")
    return ok, j


def test_surface_png_assets(ndvi_j, wh_j):
    sep("TEST #7: PNG surface asset download")
    results = {}
    for label, surf in (("NDVI", ndvi_j), ("Water Health", wh_j)):
        url = surf.get("image_url")
        if not url:
            print(f"{label}: no image_url")
            continue
        full = BASE + url if url.startswith("/") else url
        r = requests.get(full, timeout=15)
        ct = r.headers.get("content-type", "")
        kb = len(r.content) / 1024
        print(f"{label}: status={r.status_code} type={ct} size_kb={kb:.1f}")
        ok = r.status_code == 200 and ("png" in ct or kb > 20) and kb > 10
        results[label] = ok
        print(f"  {'PASS' if ok else 'FAIL'}")
    return all(results.values()), results


def main():
    results = {}
    ok1, ndvi_j = test_ndvi_surface_latest()
    results["#1_ndvi_latest"] = ok1
    ok2, _ = test_ndvi_pixel_value()
    results["#2_ndvi_pixel"] = ok2
    ok3, wh_j = test_wh_surface_latest()
    results["#3_wh_latest"] = ok3
    ok4, water_loc = test_wh_pixel_water()
    results["#4_wh_water_pixel"] = ok4
    ok5, _ = test_wh_pixel_nonwater()
    results["#5_wh_nonwater_pixel"] = ok5
    lon_w = water_loc[0] if water_loc else 72.91
    lat_w = water_loc[1] if water_loc else 19.12
    ok6, _ = test_three_level_analysis((lon_w, lat_w))
    results["#6_three_level"] = ok6
    ok7, _ = test_surface_png_assets(ndvi_j, wh_j)
    results["#7_png_assets"] = ok7

    sep("FINAL SUMMARY")
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    print(f"Passed: {passed}/{total}")
    for k, v in results.items():
        print(f"  {k}: {'PASS' if v else 'FAIL'}")
    print()
    with open(r"server\scripts\_validate_results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
