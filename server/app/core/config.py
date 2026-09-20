from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    env: str = "development"
    log_level: str = "info"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "geosense"
    db_user: str = "postgres"
    db_password: str = ""
    aqicn_token: str | None = None
    openaq_aqi_key: str | None = None
    gee_project: str | None = None
    gemini_api_key: str | None = None

    model_config = SettingsConfigDict(
        env_file=ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def parsed_cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
    
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
