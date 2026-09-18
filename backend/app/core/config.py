from pydantic_settings import BaseSettings
from functools import lru_cache
from datetime import datetime


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
    # Minimum time between manually-triggered scrapes. POST /refresh/ is now
    # admin-only (require_role), but the cooldown still matters even
    # authenticated: an admin fat-fingering the button twice shouldn't launch
    # two concurrent ~1-1.5h scrapes, and it caps how often the government
    # site gets hit regardless of who's asking.
    REFRESH_COOLDOWN_MINUTES: int = 30
    LAST_REFRESH_STARTED_AT: datetime | None = None
    # Number of states to scrape in parallel within each dimension process.
    # Each state runs in its own HTTP session with its own pacing (1.5s between
    # RTO requests), so N concurrent states means N requests every ~1.5s instead of 1.
    # Stepped 1 -> 2 -> 3 -> 4: VAHAN showed signs of bot-detection at
    # "dozens of concurrent sessions" during this session's crosstab
    # backfill. 2 ran clean for two full scrapes (2947s, 2923s); 3 ran clean
    # for one full scrape (1714s, ~1.7x faster than 2); 4 ran clean for one
    # full scrape (1282s, ~2.3x faster than 2, 34% faster than 3 -- close to
    # linear scaling, zero errors each step, confirmed via full log scan).
    # Bump further only after a clean full run is observed at the next step.
    SCRAPER_CONCURRENT_STATES: int = 4
    # Off by default: enabling this adds a full extra all-India, all-3-
    # dimension scrape (the same weight as a manual Refresh) once a day, on
    # top of the normal 5h current-year loop -- a real, standing increase in
    # load against the live government site, not a cheap check. See
    # scraper.scheduler.run_previous_year_revalidation_loop. Turn on via
    # .env once you've decided that tradeoff is worth it.
    ENABLE_PREVIOUS_YEAR_REVALIDATION: bool = False

    # Auth (hierarchy/role system). The dev default here is fine for local
    # work but MUST be overridden via .env in any real deployment -- anyone
    # who knows this string can forge a valid admin token. Not validated at
    # startup (no hard fail) to keep local dev frictionless; that tradeoff
    # only holds because this app isn't internet-facing yet.
    JWT_SECRET_KEY: str = "dev-only-change-me-in-production"
    JWT_EXPIRE_MINUTES: int = 60 * 24  # 24h

    # Connection budget. Postgres ships with max_connections=100, and every
    # process using this engine can open POOL_SIZE + MAX_OVERFLOW. The API
    # is one process; each scraper run is another, and several can run at
    # once during a backfill. At 20+40 each, four processes want 240 against
    # a ceiling of 100 -- the excess does not queue, it fails to connect.
    # Scraper entrypoints lower these via the environment (they need a
    # handful of connections, not sixty); the defaults here are sized for
    # the API, whose Overview page alone fires ~8 concurrent aggregates.
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 40

    # Applied to HTTP request sessions only (see database.get_db), not to
    # migrations, VACUUM or the scrapers -- CREATE INDEX on an 18M-row table
    # and VACUUM ANALYZE legitimately run for minutes, and killing those
    # would be worse than the runaway query this guards against. Without it
    # a single slow query holds its connection until the client gives up,
    # which is how one bad plan becomes pool exhaustion and then an outage.
    # 30s is far above any healthy request here (the slowest cold aggregate
    # measured ~3s).
    DB_STATEMENT_TIMEOUT_MS: int = 30_000

    # False by default so an omitted .env is safe. /docs, /redoc and
    # /openapi.json enumerate every route, every query parameter (including
    # the scope-clamped ones), every schema and every scope dependency --
    # a free map of the authorization surface for anyone who can reach the
    # API, which is exactly how the scope gaps found in review were located.
    # It also forces the CSP to keep script-src 'unsafe-inline' plus a CDN
    # origin, weakening the only XSS backstop. Set ENABLE_API_DOCS=true in
    # a local .env for development.
    ENABLE_API_DOCS: bool = False

    # FADA (dealer retail figures parsed from press-release PDFs) is a second
    # source, separate from VAHAN. This deployment presents VAHAN
    # registration data only -- the Industry Sales page it fed is hidden --
    # so the 24h scraper that fetches it is off by default too. Leaving it
    # running would keep hitting fada.in for data nothing displays. Set
    # ENABLE_FADA_SCRAPER=true to turn it back on alongside that page.
    ENABLE_FADA_SCRAPER: bool = False

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
