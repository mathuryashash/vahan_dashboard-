from pydantic_settings import BaseSettings
from functools import lru_cache
from datetime import datetime
import os


class Settings(BaseSettings):
    PROJECT_NAME: str = "Vahan Dashboard API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    DATABASE_URL: str = "postgresql+asyncpg://vahan:vahan@localhost:5432/vahan"
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
    # Minimum time between manually-triggered scrapes. POST /refresh/ has no
    # auth (it's a public dashboard button), so without a cooldown anyone
    # could keep re-triggering a fresh ~1-1.5h scrape back-to-back forever --
    # hammering both this app's own DB (write contention) and the government
    # site the scraper hits.
    REFRESH_COOLDOWN_MINUTES: int = 30
    LAST_REFRESH_STARTED_AT: datetime | None = None
    # Number of states to scrape in parallel within each dimension process.
    # Each state runs in its own HTTP session with its own pacing (1.5s between
    # RTO requests), so N concurrent states means N requests every ~1.5s instead of 1.
    # Default 1 preserves original serial behavior. Increase to 2-4 for higher throughput.
    SCRAPER_CONCURRENT_STATES: int = 1

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
