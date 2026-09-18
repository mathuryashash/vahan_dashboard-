"""Cap a standalone script's connection pool before the engine is built.

Every process that imports app.core.database builds its own engine at import
time, sized for the API (DB_POOL_SIZE + DB_MAX_OVERFLOW, 20 + 40). Several
scrapers plus the API share one Postgres with max_connections=100, so a script
that will never use sixty connections should not be entitled to them.

Call one of these BEFORE any app.* import. Afterwards the engine already
exists and this is a no-op -- which is the whole reason the call sites carry
`# noqa: E402` on the imports that follow them.

These are ceilings, not reservations: SQLAlchemy pools open connections on
demand, so a serial script holds ~2 either way. The point is to bound what an
unexpectedly-parallel or leaking run can take away from everyone else, and to
make each script's real appetite explicit rather than inherited from the API.
"""
import os


def _set(pool_size: int, max_overflow: int) -> None:
    # setdefault, so an explicit env var still wins.
    os.environ.setdefault("DB_POOL_SIZE", str(pool_size))
    os.environ.setdefault("DB_MAX_OVERFLOW", str(max_overflow))


def serial() -> None:
    """One session for the whole run, plus the advisory-lock connection.

    run_full_scrape, run_crosstab_scrape and backfill_fada all persist through
    a single `async with AsyncSessionLocal() as db` held open for the duration
    -- their parallelism is in concurrent HTTP requests to VAHAN, not in
    concurrent database sessions. Three connections would do; ten is slack.
    """
    _set(5, 5)


def concurrent_workers() -> None:
    """One session per --concurrent worker.

    run_analytics_scrape, run_analytics_fuel_scrape and run_top_makers_scrape
    open a session inside each worker coroutine, so the ceiling MUST exceed
    --concurrent or the workers block on the pool and time out instead of
    running. 32 covers every default (4-10) with room to raise the flag well
    past it, and is still half of what the API asks for.
    """
    _set(16, 16)
