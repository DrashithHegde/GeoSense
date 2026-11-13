"""Human-readable place names for a clicked point (e.g. "Powai, Mumbai").

Uses Mapbox reverse geocoding with the project's existing Mapbox token (VITE_MAPBOX_TOKEN in
the root .env, or MAPBOX_TOKEN). The neighbourhood / locality name comes from Mapbox; the
municipality always comes from GeoSense's own official boundaries, so the administrative unit
shown is never guessed. Results are cached in memory per ~100 m; if Mapbox is unreachable the
panel simply shows the municipality — coordinates are never needed as a name.
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.config import get_settings

_CACHE: dict[tuple[float, float], tuple[float, dict | None]] = {}
_TTL_OK = 24 * 3600.0
_TTL_FAIL = 300.0
TYPES = "neighborhood,locality,place"
PREFERENCE = ("neighborhood", "locality", "place")


def _token() -> str | None:
    s = get_settings()
    return getattr(s, "mapbox_token", None) or getattr(s, "vite_mapbox_token", None)


def parse_v6(data: dict) -> dict | None:
    feats = data.get("features") or []
    by_type: dict[str, dict] = {}
    for f in feats:
        p = f.get("properties") or {}
        by_type.setdefault(p.get("feature_type"), p)
    for t in PREFERENCE:
        p = by_type.get(t)
        if p and p.get("name"):
            ctx = p.get("context") or {}
            return {"name": p["name"], "feature_type": t,
                    "locality": (ctx.get("locality") or {}).get("name"),
                    "city": (ctx.get("place") or {}).get("name") or (p["name"] if t == "place" else None)}
    return None


def parse_v5(data: dict) -> dict | None:
    feats = data.get("features") or []
    for t in PREFERENCE:
        for f in feats:
            if t in (f.get("place_type") or []) and f.get("text"):
                city = next((c.get("text") for c in f.get("context") or [] if str(c.get("id", "")).startswith("place.")),
                            f["text"] if t == "place" else None)
                return {"name": f["text"], "feature_type": t, "locality": None, "city": city}
    return None


def label(place: dict | None, municipality: str | None) -> str | None:
    if not place:
        return municipality
    name = place["name"]
    admin = municipality or place.get("city")
    if admin and admin.lower() not in name.lower():
        return f"{name}, {admin}"
    return name


def place_name(lon: float, lat: float, municipality: str | None = None, timeout: float = 3.0) -> dict[str, Any] | None:
    key = (round(lon, 3), round(lat, 3))
    hit = _CACHE.get(key)
    now = time.time()
    if hit and now < hit[0]:
        place = hit[1]
    else:
        place = _lookup(lon, lat, timeout)
        _CACHE[key] = (now + (_TTL_OK if place else _TTL_FAIL), place)
    if not place and not municipality:
        return None
    return {**(place or {}), "municipality": municipality, "label": label(place, municipality),
            "source": "Mapbox reverse geocoding (place); GeoSense boundaries (municipality)" if place
            else "GeoSense municipality boundaries"}


def _lookup(lon: float, lat: float, timeout: float) -> dict | None:
    tok = _token()
    if not tok:
        return None
    try:
        r = httpx.get("https://api.mapbox.com/search/geocode/v6/reverse",
                      params={"longitude": lon, "latitude": lat, "types": TYPES, "language": "en",
                              "access_token": tok}, timeout=timeout)
        if r.status_code == 200:
            p = parse_v6(r.json())
            if p:
                return p
        r = httpx.get(f"https://api.mapbox.com/geocoding/v5/mapbox.places/{lon},{lat}.json",
                      params={"types": TYPES, "language": "en", "access_token": tok}, timeout=timeout)
        if r.status_code == 200:
            return parse_v5(r.json())
    except httpx.HTTPError:
        return None
    return None
