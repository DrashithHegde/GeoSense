from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()


def database_url() -> URL:
    """DATABASE_URL when set (Render / Azure / any hosted Postgres), else the DB_* parts (.env)."""
    if settings.database_url_override:
        url = make_url(settings.database_url_override.strip())
        if url.drivername in ("postgres", "postgresql"):
            url = url.set(drivername="postgresql+psycopg2")
    else:
        url = URL.create(drivername="postgresql+psycopg2", username=settings.db_user, password=settings.db_password,
                         host=settings.db_host, port=settings.db_port, database=settings.db_name)
    if settings.db_sslmode and "sslmode" not in url.query:
        url = url.update_query_dict({"sslmode": settings.db_sslmode})
    return url


engine: Engine = create_engine(
    database_url(),
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    pool_recycle=1800,          # hosted databases close idle connections
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    future=True,
)


@contextmanager
def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_database_connection() -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
