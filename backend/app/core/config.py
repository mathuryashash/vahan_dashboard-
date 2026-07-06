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
    CORS_ORIGINS: list[str] = ["*"]
    LAST_UPDATED: str | None = None

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
