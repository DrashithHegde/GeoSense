from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    env: str = "development"
    log_level: str = "info"
    # comma-separated exact origins, plus an optional regex (e.g. Vercel preview URLs)
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    cors_origin_regex: str | None = None
    # Hosted databases give one URL (Render: DATABASE_URL; Azure: build it from the parts below
    # and set DB_SSLMODE=require). When DATABASE_URL is set it wins over the DB_* parts.
    database_url_override: str | None = None
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "geosense"
    db_user: str = "postgres"
    db_password: str = ""
    db_sslmode: str | None = None
    openaq_aqi_key: str | None = None
    gee_project: str | None = None
    gemini_api_key: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    groq_api_key: str | None = None
    groq_model: str | None = None
    gemini_model: str | None = None
    llm_model: str | None = None
    # summary = AI writes only a short, checked plain-words summary + answers Ask GeoSense
    # off     = no AI calls at all (evidence write-up and knowledge-base answers only)
    ai_mode: str = "summary"
    # place names for clicked points (reverse geocoding); the frontend's token is reused
    mapbox_token: str | None = None
    vite_mapbox_token: str | None = None
    # protects the POST endpoints that rebuild data (/api/ml/run, /api/surfaces/aqi/refresh, ...)
    admin_token: str | None = None

    model_config = SettingsConfigDict(
        env_file=ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    def __init__(self, **values):
        import os
        if "database_url_override" not in values and os.getenv("DATABASE_URL"):
            values["database_url_override"] = os.getenv("DATABASE_URL")
        super().__init__(**values)

    @property
    def parsed_cors_origins(self) -> list[str]:
        return [origin.strip().rstrip("/") for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
