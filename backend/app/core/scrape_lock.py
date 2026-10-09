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
import asyncio
import contextlib
import logging
import os
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger("scrape_lock")

# Fixed classid for the 2-key advisory lock form (pg_try_advisory_lock(a, b))
# -- arbitrary, just needs to not collide with any other advisory lock this
# app might ever take (there are none today). objid is hashtext(lock_key),
# computed in SQL so callers can pass a plain descriptive string instead of
# pre-hashing it themselves.
_LOCK_CLASSID = 821520260
_TRY_LOCK = text("SELECT pg_try_advisory_lock(:classid, hashtext(:key))")
_UNLOCK = text("SELECT pg_advisory_unlock(:classid, hashtext(:key))")


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
            _TRY_LOCK,
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
            await conn.execute(_UNLOCK, {"classid": _LOCK_CLASSID, "key": lock_key})
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# One run at a time, across EVERY VAHAN scrape entry point.
#
# The per-target keys above only stop two processes writing the SAME
# (table, year). They let a manual backfill of 2019 overlap the scheduled
# 2026 refresh, a targeted re-scrape overlap a crosstab run, and so on --
# each one polite on its own, together several times the request rate the
# government site sees from a normal refresh, all fighting one connection
# pool. SCRAPE_RUN_LOCK_KEY is the single shared key every entry point takes.
#
# It is held per PROCESS with a refcount, not per call: run_scraper and
# backfill_all_years run the three dimension passes concurrently inside one
# process on purpose, and those must share the run, not exclude each other.
# Subprocesses launched by a holder (run_scraper -> run_full_scrape) inherit
# it through SCRAPE_RUN_LOCK_ENV; a standalone invocation takes it itself.
# ---------------------------------------------------------------------------
SCRAPE_RUN_LOCK_KEY = "vahan-scrape-run"
SCRAPE_RUN_LOCK_ENV = "VAHAN_SCRAPE_RUN_LOCK_HELD_BY"
_run_lock_conn = None
_run_lock_depth = 0


class ScrapeRunLockBusyError(ScrapeAlreadyRunningError):
    """Another scrape run (any entry point, any process) holds the run lock."""


@contextlib.asynccontextmanager
async def scrape_run_lock(engine: AsyncEngine, who: str = "scrape"):
    """Hold the shared run lock for the block; raise ScrapeRunLockBusyError at
    once (never queue) if another process holds it. Re-entrant within one
    process; a no-op in a child whose parent passed SCRAPE_RUN_LOCK_ENV."""
    global _run_lock_conn, _run_lock_depth
    if str(engine.url).startswith("sqlite") or os.environ.get(SCRAPE_RUN_LOCK_ENV):
        yield
        return
    async with _run_lock_guard:
        if _run_lock_depth == 0:
            await _acquire_run_lock(engine, who)
        _run_lock_depth += 1
    try:
        yield
    finally:
        _run_lock_depth -= 1
        if _run_lock_depth == 0 and _run_lock_conn is not None:
            conn, _run_lock_conn = _run_lock_conn, None
            try:
                await conn.execute(_UNLOCK, {"classid": _LOCK_CLASSID, "key": SCRAPE_RUN_LOCK_KEY})
                await conn.commit()
            except BaseException:
                # A session-level lock survives close(): returned to the pool,
                # this connection would keep "a scrape is running" alive.
                # Invalidate it so the backend session (and lock) ends.
                await conn.invalidate()
                raise
            finally:
                await conn.close()


# Serializes FIRST acquisition among coroutines of one process (three
# dimension passes entering at once must not each open a lock session).
# Binds to the running loop on first use (3.10+), so module level is fine.
_run_lock_guard = asyncio.Lock()


async def _acquire_run_lock(engine: AsyncEngine, who: str) -> None:
    global _run_lock_conn
    conn = await engine.connect()
    try:
        got = (await conn.execute(
            _TRY_LOCK,
            {"classid": _LOCK_CLASSID, "key": SCRAPE_RUN_LOCK_KEY},
        )).scalar()
        await conn.commit()  # don't leave the lock connection idle in a transaction for hours
    except BaseException:
        await conn.close()
        raise
    if got:
        # Older builds (and the owner's running server) never take the run
        # lock, only per-target keys under the same classid. Treat any of
        # those held by another backend as "a scrape is running" too.
        others = (await conn.execute(text(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND granted "
            "AND classid::bigint = :classid AND pid <> pg_backend_pid() "
            # advisory locks are per-database; pg_locks shows every database's
            "AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"
        ), {"classid": _LOCK_CLASSID})).scalar()
        await conn.commit()
        if others:
            await conn.execute(_UNLOCK,
                               {"classid": _LOCK_CLASSID, "key": SCRAPE_RUN_LOCK_KEY})
            await conn.commit()
            got = False
    if not got:
        await conn.close()
        raise ScrapeRunLockBusyError(
            f"{who}: another VAHAN scrape run holds the run lock ({SCRAPE_RUN_LOCK_KEY!r}) -- "
            "refusing to start a second one against the government site. Wait for it to finish."
        )
    _run_lock_conn = conn
    logger.info("%s: acquired scrape run lock", who)


def child_env_holding_run_lock() -> dict[str, str]:
    """Environment for a subprocess launched while this process holds the run lock."""
    return {**os.environ, SCRAPE_RUN_LOCK_ENV: str(os.getpid())}


def exit_if_run_lock_busy(exc: BaseException) -> None:
    """For __main__ blocks: a busy run lock is a clean refusal, not a crash."""
    if isinstance(exc, ScrapeRunLockBusyError):
        print(f"SCRAPE_ALREADY_RUNNING: {exc}", flush=True)
        sys.exit(SCRAPE_BUSY_EXIT_CODE)
    raise exc


# Exit code for "refused: another scrape run holds the lock". Distinct from 0
# (did work), 1 (crash) and 3 (partial).
SCRAPE_BUSY_EXIT_CODE = 4
