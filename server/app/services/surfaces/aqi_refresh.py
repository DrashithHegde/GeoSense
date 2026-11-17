"""Keep every city's AQI layer current while the backend runs.

At start-up, and then every AQI_REFRESH_HOURS (default 3), the backend rebuilds a city's AQI layer
if it was built more than AQI_REFRESH_AFTER_HOURS ago (default 6): the same steps as running
scripts/generate_aqi_station_surface.py --city <id> by hand (OpenAQ -> CPCB AQI -> IDW -> map
images), then that city's composite, whose air part comes from the AQI layer.

Safety rules:
* A failed refresh (no internet, OpenAQ down, too few fresh stations) never replaces a good layer;
  the old one stays until it passes the 48 h rule (then it is hidden, see aqi_expired).
* One refresh at a time (all cities share OpenAQ's rate limit); status per city is reported by
  /api/surfaces/aqi/latest?city=<id>.
* Only cities whose layers have been generated (a surfaces manifest exists) are refreshed.
* Off with AQI_AUTO_REFRESH=0, and skipped when no OPENAQ_AQI_KEY is set.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.cities import CITIES, current_city_id, get_city, use_city

logger = logging.getLogger(__name__)

SERVER_ROOT = Path(__file__).resolve().parents[3]
_LOCK = threading.Lock()
# STATE = the most recent refresh of any city (kept for older callers); CITY_STATE = per city
STATE: dict[str, Any] = {"running": False, "last_attempt": None, "last_result": None, "last_error": None}
CITY_STATE: dict[str, dict[str, Any]] = {
    cid: {"running": False, "last_attempt": None, "last_result": None, "last_error": None} for cid in CITIES
}


def _hours(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def enabled() -> bool:
    if os.getenv("AQI_AUTO_REFRESH", "1").strip().lower() in ("0", "false", "no", "off"):
        return False
    try:
        from app.core.config import get_settings
        key = getattr(get_settings(), "openaq_aqi_key", None)
    except Exception:
        key = None
    return bool(key or os.getenv("OPENAQ_AQI_KEY"))


def state(city_id: str | None = None) -> dict[str, Any]:
    return CITY_STATE[get_city(city_id).id]


def _manifest_path(city_id: str | None = None) -> Path:
    return get_city(city_id).data_dir / "surfaces" / "manifest.json"


def layer_age_hours(city_id: str | None = None) -> float | None:
    """Hours since the city's AQI layer was last built (None = never built / unreadable)."""
    try:
        rec = (json.loads(_manifest_path(city_id).read_text(encoding="utf-8")).get("surfaces") or {}).get("aqi") or {}
        t = datetime.fromisoformat(str(rec.get("generated_at")).replace("Z", "+00:00"))
    except Exception:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 3600.0


def needs_refresh(city_id: str | None = None) -> bool:
    age = layer_age_hours(city_id)
    return age is None or age >= _hours("AQI_REFRESH_AFTER_HOURS", 6.0)


def refresh(reason: str = "manual", city_id: str | None = None) -> dict[str, Any]:
    """Rebuild one city's AQI layer (and its composite) now. Returns a short result."""
    if city_id is not None:
        with use_city(city_id):
            return refresh(reason)
    cid = current_city_id()
    if not _LOCK.acquire(blocking=False):
        return {"status": "already_running"}
    st = CITY_STATE[cid]
    now = datetime.now(timezone.utc).isoformat()
    st.update(running=True, last_attempt=now, last_error=None)
    STATE.update(running=True, last_attempt=now, last_error=None, city=cid)
    try:
        from app.services.surfaces.aqi_station_surface import MIN_STATIONS, build_aqi_surface, eligible_stations
        from openaq.derive_aqi_grid import collect_station_aqi_points

        logger.info("AQI refresh %s (%s): fetching OpenAQ stations…", cid, reason)
        points, fetched, failures = collect_station_aqi_points(max_age_hours=48.0)
        fresh, _ = eligible_stations(points)
        if len(fresh) < MIN_STATIONS:
            # keep the layer we have; it is hidden by itself once it passes 48 h
            result = {"status": "kept_previous", "reason": f"only {len(fresh)} fresh station(s) this time"}
        else:
            rec = build_aqi_surface(points)
            result = {"status": rec["generation_status"], "stations": len(fresh), "fetched": fetched,
                      "cpcb_aqi_failures": failures}
            if rec["generation_status"] == "generated":
                _rebuild_composite()
                _prune_old_outputs()
        st["last_result"] = STATE["last_result"] = result
        logger.info("AQI refresh %s (%s): %s", cid, reason, result)
        return result
    except Exception as exc:          # offline, OpenAQ error, ... -> keep the current layer
        st.update(last_error=str(exc), last_result={"status": "failed"})
        STATE.update(last_error=str(exc), last_result={"status": "failed"})
        logger.warning("AQI refresh %s (%s) failed, keeping the current layer: %s", cid, reason, exc)
        return {"status": "failed", "error": str(exc)}
    finally:
        st["running"] = False
        STATE["running"] = False
        _LOCK.release()


def _rebuild_composite() -> None:
    """The composite's air part comes from the AQI layer, so rebuild it with the new AQI."""
    scripts = str(SERVER_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    try:
        import generate_composite_surface
        generate_composite_surface.main()
    except Exception as exc:
        logger.warning("Composite rebuild after the AQI refresh failed (the previous composite stays): %s", exc)


def _prune_old_outputs() -> None:
    """Each refresh writes new timestamped AQI and composite files; keep only the files the
    manifest points at (plus nothing else in those two folders), so the disk does not fill up."""
    try:
        from app.services.surfaces.housekeeping import prune_unreferenced
        prune_unreferenced(("aqi", "composite"))
    except Exception as exc:
        logger.warning("Could not remove old AQI/composite files: %s", exc)


def refreshable_cities() -> list[str]:
    """Cities whose layers have been generated (there is something to keep current)."""
    return [cid for cid in CITIES if _manifest_path(cid).exists()]


def start_background() -> None:
    """Called once at start-up: refresh stale cities now, then check every AQI_REFRESH_HOURS."""
    if not enabled():
        logger.info("AQI auto-refresh off (AQI_AUTO_REFRESH=0 or no OPENAQ_AQI_KEY).")
        return
    every_s = max(0.5, _hours("AQI_REFRESH_HOURS", 3.0)) * 3600.0

    def loop():
        time.sleep(20)                # let start-up (warm-up, first page load) finish first
        while True:
            for cid in refreshable_cities():
                try:
                    if needs_refresh(cid):
                        refresh("scheduled", cid)
                except Exception as exc:  # never let the thread die
                    logger.warning("AQI auto-refresh check for %s failed: %s", cid, exc)
            time.sleep(every_s)

    threading.Thread(target=loop, name="aqi-auto-refresh", daemon=True).start()
    logger.info("AQI auto-refresh on for %s: rebuilt when older than %.0f h, checked every %.1f h.",
                ", ".join(refreshable_cities()) or "no generated city yet",
                _hours("AQI_REFRESH_AFTER_HOURS", 6.0), every_s / 3600.0)
