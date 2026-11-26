"""Persistent execution log for scheduled ingestion and processing jobs."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app.database import SessionLocal


def start_run(job_name: str, city: str, layer: str, metadata: dict[str, Any] | None = None) -> int | None:
    """Insert a running record in ingestion_runs and return its id (or None if DB unavailable)."""
    now = datetime.now(timezone.utc)
    try:
        with SessionLocal() as db:
            row = db.execute(
                text("""
                    INSERT INTO ingestion_runs (job_name, city, layer, status, started_at, metadata)
                    VALUES (:job, :city, :layer, 'running', :started, CAST(:meta AS jsonb))
                    RETURNING id
                """),
                {"job": job_name, "city": city, "layer": layer, "started": now, "meta": json.dumps(metadata or {})},
            ).fetchone()
            db.commit()
            return int(row[0]) if row else None
    except Exception:
        return None


def finish_run(
    run_id: int | None,
    *,
    status: str,
    source_timestamp: datetime | None = None,
    records_processed: int | None = None,
    bundle_blob: str | None = None,
    error_message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Update an ingestion_runs row with completion status, timestamps, and error details."""
    if run_id is None:
        return
    now = datetime.now(timezone.utc)
    try:
        with SessionLocal() as db:
            db.execute(
                text("""
                    UPDATE ingestion_runs
                    SET status = :status,
                        finished_at = :finished,
                        source_timestamp = COALESCE(:src_ts, source_timestamp),
                        records_processed = COALESCE(:recs, records_processed),
                        bundle_blob = COALESCE(:blob, bundle_blob),
                        error_message = :err,
                        metadata = COALESCE(metadata, '{}'::jsonb) || CAST(:meta AS jsonb)
                    WHERE id = :id
                """),
                {
                    "id": run_id,
                    "status": status,
                    "finished": now,
                    "src_ts": source_timestamp,
                    "recs": records_processed,
                    "blob": bundle_blob,
                    "err": error_message[:2000] if error_message else None,
                    "meta": json.dumps(metadata or {}, default=str),
                },
            )
            db.commit()
    except Exception:
        pass


def recent_runs(db, city: str, limit: int = 10) -> list[dict[str, Any]]:
    """Return the most recent ingestion runs for `city` (empty list if table not present)."""
    try:
        rows = db.execute(
            text("""
                SELECT id, job_name, layer, status, started_at, finished_at,
                       source_timestamp, records_processed, bundle_blob, error_message
                FROM ingestion_runs
                WHERE city = :city
                ORDER BY started_at DESC
                LIMIT :lim
            """),
            {"city": city, "lim": limit},
        ).mappings().all()
        return [
            {
                "id": int(r["id"]),
                "job_name": r["job_name"],
                "layer": r["layer"],
                "status": r["status"],
                "started_at": r["started_at"].isoformat() if r["started_at"] else None,
                "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
                "source_timestamp": r["source_timestamp"].isoformat() if r["source_timestamp"] else None,
                "records_processed": r["records_processed"],
                "bundle_blob": r["bundle_blob"],
                "error_message": r["error_message"],
            }
            for r in rows
        ]
    except Exception:
        return []
