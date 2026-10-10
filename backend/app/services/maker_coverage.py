"""Precomputed per-maker RTO coverage for the Makers page's coverage-gap flag.

`makers_with_coverage_gaps` (core/query_filters.py) asks, for the makers on a
leaderboard: how many distinct RTOs does each one reach in the selected year,
and in its best year since (year - 5)? Answered live from
maker_category_totals that reads every row those makers have in six years --
for the national Two-Wheeler top 100 of 2011 that was 1.35M index tuples, a
hash spill to disk, 1.6 s with a warm cache and 6-9.5 s cold, on every
old-year Makers load. The answer only changes when the crosstab is
re-scraped, so it is stored in `maker_rto_coverage` and rebuilt here.

Freshness is never assumed. Each rebuild records a fingerprint of
maker_category_totals (Postgres' cumulative insert/update/delete counters for
the table plus max(id)). A reader that finds the fingerprint moved answers
from the live query instead -- same numbers, only slower -- and starts one
background rebuild. A scrape that forgets to call the hook costs speed for a
couple of minutes, never correctness. A database where the table was never
built (fresh CI/Docker) simply keeps using the live query.

**Scraper hook:** `await refresh_maker_rto_coverage(engine)` once after a run
that wrote maker_category_totals. ~9 s on the live DB (3.0M source rows ->
~238k summary rows), takes no lock on maker_category_totals, returns at once
when nothing changed since the last build, and is a no-op while another
rebuild runs.
By hand: `python -m app.services.maker_coverage` from backend/.
"""
from __future__ import annotations

import asyncio
import logging
import time

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models.models import MakerCategoryTotal, MakerRtoCoverage

logger = logging.getLogger(__name__)

# state_name of the national rows. Real state names are never empty
# (states.state_name is NOT NULL and every MCT row FK-references it).
NATIONAL = ""
META_KEY = "maker_rto_coverage"
# pg_try_advisory_xact_lock key ("MRTC"); distinct from the scrape lock.
_LOCK_KEY = 0x4D525443
# During a scrape the fingerprint moves constantly; rebuild at most this often.
_AUTO_REFRESH_MIN_INTERVAL = 300.0
_last_auto_refresh = float("-inf")
pending: asyncio.Task | None = None  # the background rebuild, for tests

# Write counters (not MVCC: they cover every committed write, deletes
# included) + max(id) (MVCC). MCT is written delete-then-insert per
# (rto, year), so any rewrite raises max(id); the counters also catch a
# delete-only write.
_COUNTERS_SQL = text(
    "SELECT pg_stat_get_tuples_inserted(c.oid)::text || ':' || pg_stat_get_tuples_updated(c.oid)::text"
    " || ':' || pg_stat_get_tuples_deleted(c.oid)::text"
    " FROM pg_class c WHERE c.oid = 'maker_category_totals'::regclass"
)
_MAX_ID_SQL = text("SELECT coalesce(max(id)::text, '-') FROM maker_category_totals")


async def _fingerprint(conn) -> str:
    return (await conn.execute(_COUNTERS_SQL)).scalar_one() + ":" + (await conn.execute(_MAX_ID_SQL)).scalar_one()


async def refresh_maker_rto_coverage(engine: AsyncEngine) -> bool:
    """Rebuild maker_rto_coverage from maker_category_totals.

    One REPEATABLE READ transaction: every row comes from one snapshot, and
    readers see the whole old table or the whole new one. The write counters
    are read on a separate statement BEFORE that snapshot exists, so the
    stored fingerprint can only be older than the data it describes -- the
    safe direction: at worst one extra rebuild, never a stale table that
    reads as current.
    Returns False, doing nothing, off Postgres or if a rebuild is running.
    """
    if engine.dialect.name != "postgresql":
        return False
    started = time.perf_counter()
    async with engine.connect() as c0:
        counters = (await c0.execute(_COUNTERS_SQL)).scalar_one()
        await c0.rollback()
    async with engine.connect() as raw:
        conn = await raw.execution_options(isolation_level="REPEATABLE READ")
        async with conn.begin():
            # Lock FIRST: in REPEATABLE READ this statement also fixes the
            # snapshot, so a rebuild that gets the lock always sees every
            # earlier rebuild's committed rows (taking it after the snapshot
            # let two rebuilds collide in a serialization failure).
            if not (await conn.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})).scalar():
                return False
            fp = counters + ":" + (await conn.execute(_MAX_ID_SQL)).scalar_one()
            stored = (await conn.execute(
                text("SELECT source_fingerprint FROM derived_table_state WHERE name = :n"), {"n": META_KEY},
            )).scalar()
            if stored == fp:
                return True  # already current: the scraper hook is free when nothing changed
            # The whole-table DISTINCT spills to disk at the stock 4MB.
            await conn.execute(text("SET LOCAL work_mem = '128MB'"))
            await conn.execute(text("DELETE FROM maker_rto_coverage"))
            # count(*) over DISTINCT (..., rto_code): the exact counting rule
            # of the live query (live_coverage below).
            await conn.execute(text(
                "INSERT INTO maker_rto_coverage (state_name, maker, year, rto_count)"
                " SELECT state_name, maker, year, count(*) FROM"
                " (SELECT DISTINCT state_name, maker, year, rto_code FROM maker_category_totals) d"
                " GROUP BY state_name, maker, year"
            ))
            await conn.execute(text(
                "INSERT INTO maker_rto_coverage (state_name, maker, year, rto_count)"
                " SELECT :nat, maker, year, count(*) FROM"
                " (SELECT DISTINCT maker, year, rto_code FROM maker_category_totals) d"
                " GROUP BY maker, year"
            ), {"nat": NATIONAL})
            await conn.execute(text(
                "INSERT INTO derived_table_state (name, source_fingerprint, refreshed_at)"
                " VALUES (:n, :fp, now())"
                " ON CONFLICT (name) DO UPDATE SET source_fingerprint = EXCLUDED.source_fingerprint,"
                " refreshed_at = EXCLUDED.refreshed_at"
            ), {"n": META_KEY, "fp": fp})
    logger.info("maker_rto_coverage rebuilt in %.1fs", time.perf_counter() - started)
    return True


def _schedule_refresh(engine: AsyncEngine) -> None:
    global _last_auto_refresh, pending
    now = time.monotonic()
    if now - _last_auto_refresh < _AUTO_REFRESH_MIN_INTERVAL or (pending is not None and not pending.done()):
        return
    _last_auto_refresh = now

    async def _run():
        try:
            await refresh_maker_rto_coverage(engine)
        except Exception:  # costs speed only: readers stay on the live query
            logger.exception("maker_rto_coverage background rebuild failed")

    pending = asyncio.get_running_loop().create_task(_run())


async def stored_coverage(
    db: AsyncSession, makers: list[str], year_floor: int, state: str | None,
) -> list[tuple[str, int, int]] | None:
    """(maker, year, rto_count) for `makers` in years > year_floor from the
    summary, or None when it was never built or is stale -- the caller then
    runs the live query."""
    if db.bind.dialect.name != "postgresql":
        return None
    stored_fp = (await db.execute(
        text("SELECT source_fingerprint FROM derived_table_state WHERE name = :n"), {"n": META_KEY},
    )).scalar()
    if stored_fp is None:
        return None
    if stored_fp != await _fingerprint(db):
        _schedule_refresh(db.bind)
        return None
    q = select(MakerRtoCoverage.maker, MakerRtoCoverage.year, MakerRtoCoverage.rto_count).where(
        MakerRtoCoverage.state_name == (state or NATIONAL),
        MakerRtoCoverage.maker.in_(makers),
        MakerRtoCoverage.year > year_floor,
    )
    return [tuple(r) for r in (await db.execute(q)).all()]


async def live_coverage(
    db: AsyncSession, model, makers: list[str], year_floor: int, state: str | None,
) -> list[tuple[str, int, int]]:
    """Distinct (maker, year, rto) first, then count per (maker, year).
    count(DISTINCT rto_code) GROUP BY maker, year forced a sort of every
    matching row that spilled to disk at work_mem=4MB (3.97s on prod); the
    inner DISTINCT is a HashAggregate (284ms) with an identical result."""
    inner = select(model.maker, model.year, model.rto_code).where(
        model.maker.in_(makers), model.year > year_floor,
    )
    if state:
        inner = inner.where(model.state_name == state)
    inner = inner.distinct().subquery()
    q = select(inner.c.maker, inner.c.year, func.count()).group_by(inner.c.maker, inner.c.year)
    return [tuple(r) for r in (await db.execute(q)).all()]


async def coverage_rows(
    db: AsyncSession, model, makers: list[str], year_floor: int, state: str | None,
) -> list[tuple[str, int, int]]:
    if model is MakerCategoryTotal:
        rows = await stored_coverage(db, makers, year_floor, state)
        if rows is not None:
            return rows
    return await live_coverage(db, model, makers, year_floor, state)


if __name__ == "__main__":  # pragma: no cover - manual rebuild
    from app.core.database import engine as _engine

    async def _main():
        ok = await refresh_maker_rto_coverage(_engine)
        await _engine.dispose()
        print("rebuilt" if ok else "skipped (not postgres, or a rebuild is running)")

    asyncio.run(_main())
