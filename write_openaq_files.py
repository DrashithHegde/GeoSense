import pathlib, textwrap

ROOT = pathlib.Path(r"C:\Users\DRASHITH HEGDE\OneDrive\Desktop\GeoSense\server")

# ───────────────────────────── client.py ──────────────────────────────────
client_src = '''"""OpenAQ v3 API client for GeoSense AQI ingestion.

Discovers Mumbai/MMR stations and fetches latest pollutant measurements.
Never fabricates missing measurements.
Provider/source label preserved for CPCB/MPCB provenance.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

MMR_BBOX = "72.77,18.89,73.12,19.40"
CPCB_PROVIDERS = {"CPCB", "caaqm", "MPCB", "BMC"}
AQI_POLLUTANTS = {"pm25", "pm10", "no2", "so2", "o3", "co"}
CO_PPB_TO_UGM3 = 1.145
OPENAQ_BASE = "https://api.openaq.org/v3"
REQUEST_TIMEOUT = 20


def _headers(api_key: str) -> Dict[str, str]:
    return {"X-API-Key": api_key}


def discover_mmr_stations(api_key: str) -> List[Dict[str, Any]]:
    """Return OpenAQ location dicts within the MMR bounding box."""
    url = f"{OPENAQ_BASE}/locations"
    params = {"bbox": MMR_BBOX, "limit": 200}
    resp = requests.get(url, params=params, headers=_headers(api_key), timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    stations = []
    for loc in data.get("results", []):
        coords = loc.get("coordinates") or {}
        lat = coords.get("latitude")
        lon = coords.get("longitude")
        if lat is None or lon is None:
            continue
        provider_name = (loc.get("provider") or {}).get("name", "Unknown")
        stations.append(
            {
                "id": loc["id"],
                "name": loc.get("name", f"OpenAQ-{loc[\'id\']}"),
                "latitude": float(lat),
                "longitude": float(lon),
                "provider": provider_name,
                "is_cpcb_mpcb": provider_name in CPCB_PROVIDERS,
                "sensors": loc.get("sensors") or [],
            }
        )
    logger.info(
        "OpenAQ: discovered %d stations in MMR bbox (%d CPCB/MPCB-backed)",
        len(stations), sum(1 for s in stations if s["is_cpcb_mpcb"]),
    )
    return stations


def _parse_utc_dt(dt_obj: Any) -> Optional[datetime]:
    if not dt_obj:
        return None
    utc_str = dt_obj.get("utc") if isinstance(dt_obj, dict) else str(dt_obj)
    if not utc_str:
        return None
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return None


def _build_sensor_map(sensors: List[Dict]) -> Dict[int, Dict]:
    m: Dict[int, Dict] = {}
    for s in sensors:
        sid = s.get("id")
        param = s.get("parameter") or {}
        if sid is not None:
            m[int(sid)] = {"param_name": param.get("name", ""), "units": param.get("units", "")}
    return m


def fetch_latest_measurements(api_key: str, location_id: int) -> List[Dict[str, Any]]:
    url = f"{OPENAQ_BASE}/locations/{location_id}/latest"
    resp = requests.get(url, headers=_headers(api_key), timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json().get("results", [])


def collect_station_pollutants(
    api_key: str,
    station: Dict[str, Any],
    max_age_hours: float = 48.0,
) -> Optional[Dict[str, Any]]:
    """Fetch and aggregate pollutant concentrations for one station.

    Returns dict with station metadata + pollutants dict, or None if no fresh data.
    Pollutants missing from the station are absent from the dict (no fabrication).
    """
    location_id = station["id"]
    sensors_meta = _build_sensor_map(station.get("sensors", []))
    try:
        raw = fetch_latest_measurements(api_key, location_id)
    except Exception as exc:
        logger.warning("OpenAQ: failed to fetch location_id=%s: %s", location_id, exc)
        return None

    pollutants: Dict[str, float] = {}
    timestamps: List[datetime] = []

    for meas in raw:
        sensor_id = meas.get("sensorsId")
        value = meas.get("value")
        dt_obj = meas.get("datetime")
        if sensor_id is None or value is None:
            continue
        sensor_info = sensors_meta.get(int(sensor_id), {})
        param_name = sensor_info.get("param_name", "").lower()
        units = sensor_info.get("units", "").lower()
        if param_name not in AQI_POLLUTANTS:
            continue
        observed_at = _parse_utc_dt(dt_obj)
        if observed_at is None:
            continue
        age_hours = (datetime.now(timezone.utc) - observed_at).total_seconds() / 3600
        if age_hours > max_age_hours:
            continue
        v = float(value)
        if param_name == "co" and "ppb" in units:
            v = v * CO_PPB_TO_UGM3
        # Prefer ug/m3; accept ppb for non-CO if no ug/m3 available
        if "\u00b5g/m" in units or "ug/m" in units:
            pollutants[param_name] = v
            timestamps.append(observed_at)
        elif param_name not in pollutants and param_name != "co":
            pollutants[param_name] = v
            timestamps.append(observed_at)

    if not timestamps:
        return None

    return {
        "station_id": location_id,
        "station_name": station["name"],
        "latitude": station["latitude"],
        "longitude": station["longitude"],
        "provider": station["provider"],
        "is_cpcb_mpcb": station["is_cpcb_mpcb"],
        "observed_at": max(timestamps),
        "pollutants": pollutants,
    }


def get_mumbai_station_measurements(
    api_key: str,
    max_age_hours: float = 48.0,
    cpcb_only: bool = False,
) -> List[Dict[str, Any]]:
    """Discover stations + collect pollutant data. Returns list of station dicts."""
    stations = discover_mmr_stations(api_key)
    if cpcb_only:
        stations = [s for s in stations if s["is_cpcb_mpcb"]]
        logger.info("OpenAQ: filtering to %d CPCB/MPCB stations", len(stations))
    results = []
    for station in stations:
        data = collect_station_pollutants(api_key, station, max_age_hours=max_age_hours)
        if data and data.get("pollutants"):
            results.append(data)
    logger.info(
        "OpenAQ: %d/%d stations returned usable measurements",
        len(results), len(stations),
    )
    return results
'''

# ───────────────────────────── cpcb_aqi.py ────────────────────────────────
cpcb_src = '''"""Indian CPCB AQI calculation from pollutant concentrations.

Implements CPCB National Air Quality Index (2014) breakpoints.
Station AQI = max of all computable pollutant sub-indices.
No fabrication: if averaging period data is unavailable, that pollutant is skipped.
Units: pm25/pm10/no2/so2/o3 in ug/m3; co in ug/m3 (internally converted to mg/m3).
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

# CPCB 24-h breakpoints: (C_low, C_high, I_low, I_high)
CPCB_BREAKPOINTS: Dict[str, list] = {
    "pm25": [
        (0,    30,    0,   50), (31,   60,   51,  100),
        (61,   90,  101,  200), (91,  120,  201,  300),
        (121, 250,  301,  400), (251, 500,  401,  500),
    ],
    "pm10": [
        (0,    50,    0,   50), (51,  100,   51,  100),
        (101, 250,  101,  200), (251, 350,  201,  300),
        (351, 430,  301,  400), (431, 600,  401,  500),
    ],
    "no2": [
        (0,    40,    0,   50), (41,   80,   51,  100),
        (81,  180,  101,  200), (181, 280,  201,  300),
        (281, 400,  301,  400), (401, 800,  401,  500),
    ],
    "so2": [
        (0,    40,    0,   50), (41,   80,   51,  100),
        (81,  380,  101,  200), (381, 800,  201,  300),
        (801, 1600, 301,  400), (1601, 2000, 401, 500),
    ],
    "o3": [
        (0,    50,    0,   50), (51,  100,   51,  100),
        (101, 168,  101,  200), (169, 208,  201,  300),
        (209, 748,  301,  400), (749, 1000, 401,  500),
    ],
    # CO breakpoints use mg/m3 in CPCB standard
    "co": [
        (0,    1.0,   0,   50), (1.1,  2.0,  51,  100),
        (2.1, 10.0, 101,  200), (10.1, 17.0, 201, 300),
        (17.1, 34.0, 301, 400), (34.1, 50.0, 401, 500),
    ],
}

CO_UGM3_TO_MGM3 = 1.0 / 1000.0


def _sub_index(concentration: float, breakpoints: list) -> Optional[float]:
    """Linear interpolation within CPCB breakpoint table."""
    for c_low, c_high, i_low, i_high in breakpoints:
        if c_low <= concentration <= c_high:
            return i_low + (concentration - c_low) * (i_high - i_low) / (c_high - c_low)
    return None


def compute_pollutant_sub_indices(
    pollutants: Dict[str, float]
) -> Dict[str, Optional[float]]:
    """Compute per-pollutant CPCB sub-indices.

    pm25/pm10/no2/so2/o3 expected in ug/m3.
    co expected in ug/m3 (converted to mg/m3 internally for CPCB breakpoints).
    Returns dict of param -> sub_index or None.
    """
    sub_indices: Dict[str, Optional[float]] = {}
    for param, bpts in CPCB_BREAKPOINTS.items():
        conc = pollutants.get(param)
        if conc is None:
            sub_indices[param] = None
            continue
        if param == "co":
            conc = conc * CO_UGM3_TO_MGM3
        sub_indices[param] = _sub_index(conc, bpts)
    return sub_indices


def compute_station_cpcb_aqi(
    pollutants: Dict[str, float]
) -> Tuple[Optional[int], Optional[str], Dict[str, Optional[float]]]:
    """Compute station-level CPCB AQI.

    Returns (aqi, dominant_pollutant, sub_indices).
    aqi is None if no valid sub-index can be computed.
    """
    sub_indices = compute_pollutant_sub_indices(pollutants)
    valid = {p: v for p, v in sub_indices.items() if v is not None}
    if not valid:
        return None, None, sub_indices
    dominant = max(valid, key=lambda p: valid[p])
    aqi = int(round(valid[dominant]))
    return aqi, dominant, sub_indices
'''

# ───────────────────────────── derive_aqi_grid.py ─────────────────────────
derive_src = '''"""Derive CPCB AQI for GeoSense zones using OpenAQ measurements and IDW.

Replaces AQICN as the primary AQI ingestion path.
No destructive DB operations. Historical AQICN data preserved.

Freshness policy:
  fresh:       < 6 hours
  stale:       6-48 hours (accepted but labelled)
  unavailable: > 48 hours (rejected)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from statistics import mean
from typing import Dict, List, Optional, Tuple

from sqlalchemy import text

from app.database import get_db
from app.core.config import get_settings
from app.services.source_metadata import ensure_compatible_metadata, metadata_payload
from server.openaq.client import get_mumbai_station_measurements
from server.openaq.cpcb_aqi import compute_station_cpcb_aqi
from server.aqicn.derive_aqi_grid import get_zone_points, haversine_m

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

FRESH_THRESHOLD_HOURS = 6.0
STALE_THRESHOLD_HOURS = 48.0
PROVENANCE = "openaq_cpcb_idw"


def freshness_label(observed_at: datetime) -> str:
    age_h = (datetime.now(timezone.utc) - observed_at).total_seconds() / 3600
    if age_h <= FRESH_THRESHOLD_HOURS:
        return "fresh"
    if age_h <= STALE_THRESHOLD_HOURS:
        return "stale"
    return "unavailable"


def idw_estimate(
    zone_lat: float,
    zone_lon: float,
    points: List[Dict],
    k: int,
    max_interp_distance_m: float,
    min_stations: int,
    power: float,
) -> Tuple[Optional[float], Optional[float], int]:
    dlist = []
    for p in points:
        d = haversine_m(zone_lat, zone_lon, p["lat"], p["lon"])
        if d <= max_interp_distance_m:
            dlist.append((d, p["aqi"]))
    if not dlist:
        return None, None, 0
    dlist.sort(key=lambda x: x[0])
    selected = dlist[:k]
    if len(selected) < min_stations:
        return None, None, len(selected)
    if selected[0][0] == 0:
        return float(selected[0][1]), 0.0, len(selected)
    weights = [1.0 / (d ** power) for d, _ in selected]
    vals = [v for _, v in selected]
    total_w = sum(weights)
    if total_w == 0:
        return None, None, len(selected)
    est = sum(w * v for w, v in zip(weights, vals)) / total_w
    return float(est), float(selected[0][0]), len(selected)


def upsert_openaq_aqi(
    db,
    zone_id: int,
    observed_at: datetime,
    aqi: Optional[int],
    source_type: Optional[str],
    nearest_dist_m: Optional[float],
    source_context: Optional[dict] = None,
):
    ensure_compatible_metadata(
        db, zone_id=zone_id, observed_at=observed_at, key="aqi", context=source_context,
    )
    db.execute(
        text(
            """
            INSERT INTO environment_data (
                zone_id, observed_at, aqi, aqi_source_type,
                aqi_nearest_station_distance_m, source_metadata
            )
            VALUES (:z, :obs, :aqi, :src, :dist, CAST(:metadata AS jsonb))
            ON CONFLICT (zone_id, observed_at)
            DO UPDATE SET
                aqi = EXCLUDED.aqi,
                aqi_source_type = EXCLUDED.aqi_source_type,
                aqi_nearest_station_distance_m = EXCLUDED.aqi_nearest_station_distance_m,
                source_metadata = environment_data.source_metadata || EXCLUDED.source_metadata
            """
        ),
        {
            "z": zone_id, "obs": observed_at,
            "aqi": int(round(aqi)) if aqi is not None else None,
            "src": source_type, "dist": nearest_dist_m,
            "metadata": metadata_payload("aqi", source_context),
        },
    )


def run_openaq_derivation(
    k: int = 4,
    max_interp_distance_m: float = 20000.0,
    min_stations: int = 2,
    power: float = 2.0,
    station_assign_distance_m: int = 8000,
    max_age_hours: float = 48.0,
) -> Dict:
    """Fetch OpenAQ data, compute CPCB AQI, IDW to 189 zones.

    Raises RuntimeError if API key missing or no usable stations.
    Does NOT fall back to AQICN silently.
    """
    api_key = get_settings().openaq_aqi_key
    if not api_key:
        raise RuntimeError("OPENAQ_AQI_KEY not configured")

    raw_stations = get_mumbai_station_measurements(
        api_key, max_age_hours=max_age_hours, cpcb_only=False
    )
    if not raw_stations:
        raise RuntimeError("OpenAQ returned no usable station measurements for MMR")

    station_points = []
    cpcb_failures = 0
    for s in raw_stations:
        aqi_val, dominant, sub_indices = compute_station_cpcb_aqi(s["pollutants"])
        if aqi_val is None:
            cpcb_failures += 1
            continue
        station_points.append({
            "station_id": s["station_id"],
            "station_name": s["station_name"],
            "lat": s["latitude"],
            "lon": s["longitude"],
            "provider": s["provider"],
            "is_cpcb_mpcb": s["is_cpcb_mpcb"],
            "aqi": float(aqi_val),
            "dominant_pollutant": dominant,
            "observed_at": s["observed_at"],
        })
        logger.info(
            "Station %s: CPCB AQI=%d dominant=%s freshness=%s provider=%s",
            s["station_name"], aqi_val, dominant, freshness_label(s["observed_at"]), s["provider"],
        )

    if not station_points:
        raise RuntimeError("No stations with computable CPCB AQI found")

    observed_at = max(p["observed_at"] for p in station_points)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)

    source_context = {
        "source": "OpenAQ",
        "aqi_method": "CPCB_National_AQI_2014",
        "interpolation": "IDW",
        "provenance": PROVENANCE,
        "k": k, "power": power,
        "max_interpolation_distance_m": max_interp_distance_m,
        "minimum_stations": min_stations,
        "stations_used": len(station_points),
        "stations_cpcb_mpcb": sum(1 for p in station_points if p["is_cpcb_mpcb"]),
        "fallback_used": False,
    }

    with get_db() as db:
        zone_points = get_zone_points(db)
        observed_count = 0
        estimated_count = 0
        uncovered_count = 0
        aqi_vals = []
        sample_rows = []

        for z in zone_points:
            zid = int(z["id"])
            zlat = float(z["lat"])
            zlon = float(z["lon"])

            direct = None
            for sp in station_points:
                dist = haversine_m(zlat, zlon, sp["lat"], sp["lon"])
                if dist <= station_assign_distance_m:
                    if direct is None or dist < direct[1]:
                        direct = (sp, dist)

            if direct is not None and direct[1] <= 1000:
                aqi_val = direct[0]["aqi"]
                source_type = "openaq_observed"
                nearest = direct[1]
                observed_count += 1
            else:
                est, nearest, used = idw_estimate(
                    zlat, zlon, station_points,
                    k=k, max_interp_distance_m=max_interp_distance_m,
                    min_stations=min_stations, power=power,
                )
                aqi_val = est
                if aqi_val is None:
                    source_type = None
                    uncovered_count += 1
                else:
                    source_type = PROVENANCE
                    estimated_count += 1

            if aqi_val is not None:
                aqi_vals.append(aqi_val)

            upsert_openaq_aqi(
                db, zid, observed_at,
                int(round(aqi_val)) if aqi_val is not None else None,
                source_type, nearest,
                source_context=source_context if aqi_val is not None else None,
            )

            if len(sample_rows) < 15:
                sample_rows.append({
                    "zone_id": zid,
                    "aqi": int(round(aqi_val)) if aqi_val is not None else None,
                    "source_type": source_type,
                    "nearest_station_distance_m": round(nearest, 2) if nearest is not None else None,
                })

        db.commit()

    coverage = (observed_count + estimated_count) / len(zone_points) * 100.0 if zone_points else 0.0
    return {
        "source": "OpenAQ",
        "aqi_method": "CPCB_National_AQI_2014",
        "provenance": PROVENANCE,
        "stations_fetched": len(raw_stations),
        "stations_with_cpcb_aqi": len(station_points),
        "stations_cpcb_mpcb": sum(1 for p in station_points if p["is_cpcb_mpcb"]),
        "cpcb_aqi_failures": cpcb_failures,
        "zones_total": len(zone_points),
        "zones_observed": observed_count,
        "zones_estimated": estimated_count,
        "zones_uncovered": uncovered_count,
        "coverage_percent": round(coverage, 2),
        "aqi_min": round(min(aqi_vals), 2) if aqi_vals else None,
        "aqi_max": round(max(aqi_vals), 2) if aqi_vals else None,
        "aqi_mean": round(mean(aqi_vals), 2) if aqi_vals else None,
        "observed_at": observed_at.isoformat(),
        "freshness": freshness_label(observed_at),
        "sample": sample_rows,
    }
'''

openaq_dir = ROOT / "openaq"
openaq_dir.mkdir(exist_ok=True)
(openaq_dir / "__init__.py").write_text("", encoding="utf-8")
(openaq_dir / "client.py").write_text(client_src, encoding="utf-8")
(openaq_dir / "cpcb_aqi.py").write_text(cpcb_src, encoding="utf-8")
(openaq_dir / "derive_aqi_grid.py").write_text(derive_src, encoding="utf-8")

for f in ["client.py", "cpcb_aqi.py", "derive_aqi_grid.py"]:
    p = openaq_dir / f
    print(f"{f}: {p.stat().st_size} bytes")
print("Done")
