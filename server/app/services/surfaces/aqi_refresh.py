"""Keep the AQI layer current while the backend runs.

At start-up, and then every AQI_REFRESH_HOURS (default 3), the backend rebuilds the AQI layer if it
was built more than AQI_REFRESH_AFTER_HOURS ago (default 6): the same steps as running
scripts/generate_aqi_station_surface.py by hand (OpenAQ -> CPCB AQI -> IDW -> map images), then
the composite, whose air part comes from the AQI layer.

Safety rules:
* A failed refresh (no internet, OpenAQ down, too few fresh stations) never replaces a good layer;
  the old one stays until it passes the 48 h rule (then it is hidden, see aqi_expired).
* One refresh at a time; the status is reported by /api/surfaces/aqi/latest.
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

logger = logging.getLogger(__name__)

SERVER_ROOT = Path(__file__).resolve().parents[3]
_LOCK = threading.Lock()
STATE: dict[str, Any] = {"running": False, "last_attempt": None, "last_result": None, "last_error": None}


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


def layer_age_hours() -> float | None:
    """Hours since the AQI layer was last built (None = never built / unreadable)."""
    from app.services.surfaces.aqi_station_surface import MANIFEST_PATH
    try:
        rec = (json.loads(MANIFEST_PATH.read_text(encoding="utf-8")).get("surfaces") or {}).get("aqi") or {}
        t = datetime.fromisoformat(str(rec.get("generated_at")).replace("Z", "+00:00"))
    except Exception:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 3600.0


def needs_refresh() -> bool:
    age = layer_age_hours()
    return age is None or age >= _hours("AQI_REFRESH_AFTER_HOURS", 6.0)


def refresh(reason: str = "manual") -> dict[str, Any]:
    """Rebuild the AQI layer (and the composite) now. Returns a short result."""
    if not _lock_acquire():
        return {"status": "already_running"}
    STATE.update(running=True, last_attempt=datetime.now(timezone.utc).isoformat(), last_error=None)
    try:
        from app.services.surfaces.aqi_station_surface import MIN_STATIONS, build_aqi_surface, eligible_stations
        from openaq.derive_aqi_grid import collect_station_aqi_points

        logger.info("AQI refresh (%s): fetching OpenAQ stations…", reason)
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
        STATE["last_result"] = result
        logger.info("AQI refresh (%s): %s", reason, result)
        return result
    except Exception as exc:          # offline, OpenAQ error, ... -> keep the current layer
        STATE.update(last_error=str(exc), last_result={"status": "failed"})
        logger.warning("AQI refresh (%s) failed, keeping the current layer: %s", reason, exc)
        return {"status": "failed", "error": str(exc)}
    finally:
        STATE["running"] = False
        _LOCK.release()


def _lock_acquire() -> bool:
    return _LOCK.acquire(blocking=False)


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


def start_background() -> None:
    """Called once at start-up: refresh now if needed, then check every AQI_REFRESH_HOURS."""
    if not enabled():
        logger.info("AQI auto-refresh off (AQI_AUTO_REFRESH=0 or no OPENAQ_AQI_KEY).")
        return
    every_s = max(0.5, _hours("AQI_REFRESH_HOURS", 3.0)) * 3600.0

    def loop():
        time.sleep(20)                # let start-up (warm-up, first page load) finish first
        while True:
            try:
                if needs_refresh():
                    refresh("scheduled")
            except Exception as exc:  # never let the thread die
                logger.warning("AQI auto-refresh check failed: %s", exc)
            time.sleep(every_s)

    threading.Thread(target=loop, name="aqi-auto-refresh", daemon=True).start()
    logger.info("AQI auto-refresh on: rebuilt when older than %.0f h, checked every %.1f h.",
                _hours("AQI_REFRESH_AFTER_HOURS", 6.0), every_s / 3600.0)