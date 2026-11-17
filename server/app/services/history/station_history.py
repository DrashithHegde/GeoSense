"""Station AQI history from OpenAQ v3 daily aggregates (runs on the user's machine).

For each CPCB-network station: daily means of PM2.5, PM10, NO2 and SO2 (sensors/{id}/days),
kept only when the day has >= 16 of 24 hourly values (CPCB's 24-h averaging needs adequate
coverage), converted to µg/m³, then the CPCB sub-index per pollutant and the daily CPCB AQI
(needs >= 3 pollutants including a particulate, as in the live pipeline).

O3 and CO use 8-hour averages in the CPCB AQI; OpenAQ's daily aggregates do not provide the
8-hour maximum, so they are left out of the historical AQI rather than approximated. This is
recorded in the method text, and it means historical AQI can be slightly lower than an AQI
that includes O3/CO.

Seasonal value per station = median daily AQI (and 90th percentile) over the season's days,
only when at least 15 days have a valid AQI.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Any

import numpy as np

HISTORY_POLLUTANTS = ("pm25", "pm10", "no2", "so2", "nh3")
MIN_DAY_COVERAGE_PCT = 100 * 16 / 24
MIN_DAYS_PER_SEASON = 15
METHOD = ("Daily CPCB AQI from OpenAQ daily means of PM2.5, PM10, NO2, SO2, NH3 where reported (days with >= 16 h of data; "
          ">= 3 pollutants incl. a particulate); O3/CO excluded (no 8-h maxima in daily aggregates); "
          "seasonal median of daily AQI, >= 15 days required.")


def _day(rec: dict) -> date | None:
    per = rec.get("period") or {}
    dt = ((per.get("datetimeFrom") or {}).get("local") or (per.get("datetimeFrom") or {}).get("utc")
          or (rec.get("date") or {}).get("local"))
    if not dt:
        return None
    try:
        return datetime.fromisoformat(str(dt).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def parse_days(results: list[dict], pollutant: str, units: str) -> dict[date, float]:
    """OpenAQ /days records -> {day: mean concentration in µg/m³}, adequately covered days only."""
    from openaq.client import normalize_concentration

    out: dict[date, float] = {}
    for rec in results:
        d = _day(rec)
        cov = (rec.get("coverage") or {}).get("percentComplete")
        if d is None or rec.get("value") is None:
            continue
        if cov is not None and float(cov) < MIN_DAY_COVERAGE_PCT:
            continue
        u = units or ((rec.get("parameter") or {}).get("units") or "")
        v = normalize_concentration(rec["value"], u, pollutant)
        if v is not None:
            out[d] = v
    return out


def daily_aqi(by_pollutant: dict[str, dict[date, float]]) -> dict[date, dict[str, Any]]:
    from openaq.cpcb_aqi import compute_station_cpcb_aqi

    days = sorted({d for series in by_pollutant.values() for d in series})
    out = {}
    for d in days:
        conc = {p: s[d] for p, s in by_pollutant.items() if d in s}
        aqi, dom, sub = compute_station_cpcb_aqi(conc)
        if aqi is not None:
            out[d] = {"aqi": aqi, "dominant": dom, "sub": {k: v for k, v in sub.items() if v is not None}}
    return out


def season_aggregate(days: dict[date, dict[str, Any]], start: date, end: date) -> dict[str, Any] | None:
    sel = [v for d, v in days.items() if start <= d <= end]
    if len(sel) < MIN_DAYS_PER_SEASON:
        return None
    a = np.array([v["aqi"] for v in sel], dtype=float)
    subs: dict[str, list[float]] = defaultdict(list)
    for v in sel:
        for k, x in v["sub"].items():
            subs[k].append(x)
    return {"days_with_aqi": len(sel), "aqi_median": round(float(np.median(a)), 1),
            "aqi_p90": round(float(np.percentile(a, 90)), 1),
            "dominant_pollutant": Counter(v["dominant"] for v in sel).most_common(1)[0][0],
            "sub_index_medians": {k: round(float(np.median(x)), 1) for k, x in subs.items() if len(x) >= MIN_DAYS_PER_SEASON}}


def fetch_sensor_days(api_key: str, sensor_id: int, date_from: date, date_to: date) -> list[dict]:
    from openaq.client import OPENAQ_BASE, REQUEST_TIMEOUT, _headers, _pace_sensor_history_request, _request

    out: list[dict] = []
    for page in range(1, 10):
        _pace_sensor_history_request()
        r = _request("GET", f"{OPENAQ_BASE}/sensors/{sensor_id}/days",
                     params={"date_from": date_from.isoformat(), "date_to": date_to.isoformat(),
                             "limit": 1000, "page": page},
                     headers=_headers(api_key), timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        rows = r.json().get("results", [])
        out.extend(rows)
        if len(rows) < 1000:
            break
    return out


def build_station_history(api_key: str, season_list, today: date | None = None) -> list[dict[str, Any]]:
    from openaq.client import discover_stations

    today = today or date.today()
    first = min(s.start for s in season_list)
    stations = [s for s in discover_stations(api_key) if s["is_cpcb_mpcb"]]
    rows = []
    for st in stations:
        by_p: dict[str, dict[date, float]] = {}
        for sensor in st.get("sensors") or []:
            p = ((sensor.get("parameter") or {}).get("name") or "").lower().replace(".", "")
            p = {"ammonia": "nh3"}.get(p, p)
            if p not in HISTORY_POLLUTANTS or p in by_p:
                continue
            try:
                res = fetch_sensor_days(api_key, int(sensor["id"]), first, today)
            except Exception as exc:  # one failing sensor never stops the run
                print(f"  {st['name']} {p}: {exc!s:.100}")
                continue
            by_p[p] = parse_days(res, p, (sensor.get("parameter") or {}).get("units", ""))
        days = daily_aqi(by_p)
        for s in season_list:
            agg = season_aggregate(days, s.start, s.end)
            if agg:
                rows.append({"station_id": int(st["id"]), "station_name": st["name"], "lat": st["latitude"],
                             "lon": st["longitude"], "season": s.key, "method": METHOD, **agg})
        print(f"  {st['name']}: {len(days)} days with AQI")
    return rows
