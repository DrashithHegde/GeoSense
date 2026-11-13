"""Guard for endpoints that start heavy jobs (the full ML pipeline).

* Allowed from this computer (localhost) when no ADMIN_TOKEN is set — the normal local demo.
* From anywhere else only with header  X-Admin-Token: <ADMIN_TOKEN>  (set ADMIN_TOKEN in .env).
* One run at a time: a second request while a run is going gets 409 instead of starting a
  second pipeline that would write the same tables at the same time.
"""
from __future__ import annotations

import hmac
import os
import threading

from fastapi import HTTPException, Request

_LOCAL = {"127.0.0.1", "::1", "localhost"}
PIPELINE_LOCK = threading.Lock()


def require_admin(request: Request) -> None:
    token = os.getenv("ADMIN_TOKEN", "").strip()
    given = request.headers.get("x-admin-token", "")
    if token:
        if not hmac.compare_digest(given, token):
            raise HTTPException(status_code=403, detail="Admin token required.")
        return
    host = request.client.host if request.client else ""
    if host not in _LOCAL:
        raise HTTPException(status_code=403, detail="Only allowed from this computer (or set ADMIN_TOKEN).")


def run_exclusive(job) -> None:
    """Run job() unless another pipeline run holds the lock (then do nothing)."""
    if not PIPELINE_LOCK.acquire(blocking=False):
        return
    try:
        job()
    finally:
        PIPELINE_LOCK.release()