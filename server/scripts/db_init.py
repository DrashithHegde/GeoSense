"""Prepare a database for GeoSense: PostGIS + pgvector extensions, then all migrations.

    python scripts/db_init.py            (DATABASE_URL or the DB_* settings in .env)

Run automatically when the server container starts (deploy/start.sh). Safe to run again.
Render: both extensions are supported (CREATE EXTENSION works on PostgreSQL 13+).
Azure Database for PostgreSQL flexible server: allow-list them first
(server parameter azure.extensions = POSTGIS,VECTOR), see deploy/DEPLOY.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT))


def main() -> int:
    from sqlalchemy import text

    from app.database import database_url, engine

    for ext, needed in (("postgis", True), ("vector", False)):
        try:
            with engine.begin() as c:
                c.execute(text(f"CREATE EXTENSION IF NOT EXISTS {ext}"))
            print(f"extension {ext}: ok")
        except Exception as exc:
            msg = str(exc).splitlines()[0]
            if needed:
                print(f"extension {ext}: FAILED ({msg})")
                return 1
            print(f"extension {ext}: not available ({msg}) - RAG vectors will be searched in memory")

    from alembic import command
    from alembic.config import Config

    cfg = Config(str(SERVER_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVER_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url().render_as_string(hide_password=False).replace("%", "%%"))
    command.upgrade(cfg, "head")
    print("migrations: at head")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
