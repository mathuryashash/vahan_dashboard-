"""Batch pre-warm of MakerLiveQueryCache for the top N makers by real
national volume (from MakerCategoryTotal, real batch-scraped data) across
every state and year -- turns the on-demand live-maker-lookup into an
instant lookup for the makers people actually search for most, without
attempting the infeasible full 7,733-maker cross product (see
MakerLiveQueryCache's own docstring for why that's out of reach).

Reuses get_or_scrape_maker_query directly rather than reimplementing any
scraping/caching logic -- month-level granularity, caching, and the
session pool all come for free from that function; this is purely a
driver loop over (maker, state, year) triples, same lock-per-year +
gather structure as run_analytics_fuel_scrape.py.

Benchmarked live: maker-filtered queries run slower than the plain
state/fuel scrapers (~1.5 req/s at concurrency 8-12 on the pooled-session
path; concurrency 16 showed real errors, not just diminishing returns) --
100 makers x 36 states x 24 years = 86,400 combos is a genuine multi-hour
background job, not a quick one.

Usage: python -m scraper.run_top_makers_scrape [--limit 100] [--from-year 2003] [--to-year 2026] [--concurrent 10]
"""
import argparse
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal, engine, init_db
from app.core.scrape_lock import scrape_write_lock
from app.models.models import MakerCategoryTotal, State
from app.services import live_scrape_service
from app.services.live_scrape_service import TesseractUnavailableError, get_or_scrape_maker_query
from scraper.analytics_scraper import CaptchaSolveError, verify_tesseract

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("run_top_makers_scrape")


async def _top_makers(db, limit: int) -> list[str]:
    rows = (await db.execute(
        select(MakerCategoryTotal.maker, func.sum(MakerCategoryTotal.count).label("total"))
        .group_by(MakerCategoryTotal.maker)
        .order_by(func.sum(MakerCategoryTotal.count).desc())
        .limit(limit)
    )).all()
    return [maker for maker, _ in rows]


async def _state_list(db) -> list[tuple[str, str]]:
    result = await db.execute(select(State.state_code, State.state_name))
    return result.all()


async def _run_year(makers: list[str], states: list[tuple[str, str]], year: int, concurrent: int) -> None:
    # Own local gate on the DB session itself, not just on the scrape
    # inside get_or_scrape_maker_query -- that function's own _concurrency
    # semaphore is reached only AFTER a cache-check SELECT + lock + second
    # cache-check on an already-open session, so without this, up to
    # len(makers)*len(states) sessions (thousands at default --limit) would
    # all queue for a DB connection at once against a pool capped at
    # pool_size+max_overflow=60 -- the exact pool-exhaustion failure mode
    # database.py's own pool comment warns about, and one that can starve
    # the live API sharing that same pool. Mirrors run_analytics_fuel_scrape.py's
    # sem usage, which gates its whole worker body the same way.
    sem = asyncio.Semaphore(concurrent)

    async def worker(maker: str, state_code: str) -> None:
        # Own session per concurrent call -- SQLAlchemy AsyncSessions
        # aren't safe to share across coroutines running at once.
        # get_or_scrape_maker_query checks its cache first, so a combo
        # already scraped (by this job or a live user) is a fast no-op
        # read here, not a re-scrape -- no separate resumability
        # tracking needed on top of that.
        try:
            async with sem, AsyncSessionLocal() as db:
                await get_or_scrape_maker_query(db, state_code, year, maker)
        except TesseractUnavailableError:
            # Not a per-combo failure -- every remaining maker would fail
            # identically (same reasoning as get_top_makers_leaderboard's
            # _one()), so let it propagate and abort the run loudly instead
            # of burning hours logging the same root cause per combo.
            raise
        except CaptchaSolveError as e:
            logger.warning("maker=%r state=%s year=%d: %s -- skipping", maker, state_code, year, e)
        except Exception:
            # One bad combo (a network blip, an unexpected bug) shouldn't
            # abort the other ~3,599 for this year -- same isolation
            # principle as every other scraper in this codebase. Unlike
            # the expected CaptchaSolveError above, this keeps the
            # traceback since it may be a real bug worth diagnosing later.
            logger.exception("maker=%r state=%s year=%d: unexpected failure -- skipping", maker, state_code, year)

    await asyncio.gather(*(worker(maker, code) for maker in makers for code, _ in states))


async def main(limit: int, from_year: int, to_year: int, concurrent: int) -> None:
    logger.info("Starting top-%d makers scrape (years=%d-%d, concurrent=%d) at %s",
                limit, from_year, to_year, concurrent, datetime.now(timezone.utc))
    await init_db()
    await verify_tesseract()
    # This job's own concurrency, independent of whatever the live API
    # server's process has set -- separate OS processes, separate module
    # state, no shared semaphore instance to fight over.
    live_scrape_service._concurrency = asyncio.Semaphore(concurrent)

    async with AsyncSessionLocal() as db:
        makers = await _top_makers(db, limit)
        states = await _state_list(db)

    total_combos = len(makers) * len(states) * (to_year - from_year + 1)
    logger.info("Resolved top %d makers, %d states -- %d combos across %d years",
                len(makers), len(states), total_combos, to_year - from_year + 1)

    for year in range(from_year, to_year + 1):
        lock_key = f"maker_live_query_cache:{year}"
        try:
            async with scrape_write_lock(engine, lock_key):
                logger.info("year=%d: starting (%d maker x state combos)", year, len(makers) * len(states))
                await _run_year(makers, states, year, concurrent)
                logger.info("year=%d: done", year)
        except Exception:
            # Lock contention or a DB hiccup shouldn't abort every other
            # year in the range.
            logger.exception("year=%d: failed, moving to next year", year)

    logger.info("Top-%d makers scrape complete (years=%d-%d).", limit, from_year, to_year)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100, help="How many top makers (by real national volume) to pre-warm")
    parser.add_argument("--from-year", type=int, default=2003)
    parser.add_argument("--to-year", type=int, default=2026)
    parser.add_argument("--concurrent", type=int, default=10, help="Concurrent maker/state combos per year")
    args = parser.parse_args()
    asyncio.run(main(args.limit, args.from_year, args.to_year, args.concurrent))
