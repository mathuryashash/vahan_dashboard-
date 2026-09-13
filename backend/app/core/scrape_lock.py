"""Cross-process coordination for scrape-writing entrypoints.

REFRESH_STATUS (app.core.config) is a plain Python variable, invisible to a
separate OS process -- confirmed live: none of the standalone backfill
scripts (run_full_scrape.py, run_crosstab_scrape.py, backfill_fada.py)
reference it at all, so nothing stops one of them from running concurrently
with the scheduled loop, another backfill, or a duplicate invocation of
itself. That's exactly the historical cause of the duplicate-row
accumulation cleaned up earlier (see migrations.py's ensure_no_duplicate_rows
docstring) -- and now that real unique constraints exist on the affected
tables, the same overlap crashes with an uncaught IntegrityError instead of
silently duplicating.

A Postgres advisory lock coordinates across processes for free: it's a
session-scoped lock held via one live connection to the shared DB, no new
dependency, no separate coordination service. Keyed per (write target,
year), not one single global lock -- a single global lock would serialize
the 3 concurrent dimension processes run_scraper() launches on purpose
(they write disjoint scopes: is_supplementary/fuel_type differ per
dimension, so real concurrent writes there are already safe), which would
be a regression, not a fix. The actual collision this guards against is
narrower: two different processes writing the *same* target and year.
"""
import contextlib
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger("scrape_lock")

# Fixed classid for the 2-key advisory lock form (pg_try_advisory_lock(a, b))
# -- arbitrary, just needs to not collide with any other advisory lock this
# app might ever take (there are none today). objid is hashtext(lock_key),
# computed in SQL so callers can pass a plain descriptive string instead of
# pre-hashing it themselves.
_LOCK_CLASSID = 821520260


class ScrapeAlreadyRunningError(RuntimeError):
    """Another process already holds this scrape-write lock."""


@contextlib.asynccontextmanager
async def scrape_write_lock(engine: AsyncEngine, lock_key: str):
    """Acquire the named cross-process lock for the `async with` block,
    raising ScrapeAlreadyRunningError immediately (never blocking) if
    another process already holds it -- a long-running scrape should fail
    fast and loud, not queue silently behind another one.

    No-op on SQLite: advisory locks are a Postgres-only concept, and
    SQLite here is dev-only convenience, never a real concurrent-process
    deployment target (see ensure_bigint_id/ensure_no_duplicate_rows for
    the same SQLite-skip pattern elsewhere in this codebase).

    `lock_key` should identify exactly what's being written, e.g.
    f"registrations:{dimension}:{year}" or f"maker_category_totals:{year}"
    -- two calls with the same key from different processes conflict; two
    calls with different keys (different dimension, table, or year) don't.
    """
    if str(engine.url).startswith("sqlite"):
        yield
        return

    conn = await engine.connect()
    try:
        got_lock = (await conn.execute(
            text("SELECT pg_try_advisory_lock(:classid, hashtext(:key))"),
            {"classid": _LOCK_CLASSID, "key": lock_key},
        )).scalar()
        if not got_lock:
            raise ScrapeAlreadyRunningError(
                f"Another process already holds the scrape-write lock for {lock_key!r} -- "
                "check for an overlapping backfill script or the scheduled loop."
            )
        logger.info("Acquired scrape-write lock for %r", lock_key)
        try:
            yield
        finally:
            await conn.execute(text("SELECT pg_advisory_unlock(:classid, hashtext(:key))"), {"classid": _LOCK_CLASSID, "key": lock_key})
    finally:
        await conn.close()
