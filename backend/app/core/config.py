from pydantic_settings import BaseSettings
from functools import lru_cache
import os


class Settings(BaseSettings):
    PROJECT_NAME: str = "Vahan Dashboard API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/vahan.db"
    SCRAPER_DATA_DIR: str = "./data"
    LOG_LEVEL: str = "INFO"
    # No wildcard: "*" would let any website on the internet make credentialed
    # requests to this API (e.g. trigger /refresh/ from a victim's browser).
    # CORS_ORIGINS is for explicit production origins (set via env); the regex
    # below covers local dev, where Vite's port varies (3000, 3001, ...).
    CORS_ORIGINS: list[str] = []
    CORS_ORIGIN_REGEX: str | None = r"^http://(localhost|127\.0\.0\.1):\d+$"
    LAST_UPDATED: str | None = None
    REFRESH_STATUS: str = "idle"  # idle | running | success | error
    REFRESH_ERROR: str | None = None

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
