"""Fuel-filtered sibling of run_analytics_scrape.py -- state x month x
vehicle-category totals scoped to one fuel type at a time (see
analytics_scraper.FUEL_VALUES, a static 34-value enum). Same lock-per-year +
resume-by-natural-key structure, just with (state, fuel) pairs instead of
plain states as the per-year work list -- 36 states x 34 fuels = 1,224
combos/year, ~29K total across 2003-2026.

Deliberately fuel-only: the site's maker list is a 7,733-item long tail
behind a lazy-load search endpoint, not a static enum like fuel, so there's
no run_analytics_maker_scrape.py sibling yet -- see
StateMonthCategoryFuelTotal's docstring for why that needs its own scoping
decision (e.g. top-N by volume) before a full loop like this one makes sense
for makers.

Usage: python -m scraper.run_analytics_fuel_scrape --from-year 2003 --to-year 2026 [--concurrent 8] [--force]
"""
import argparse
import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import distinct, select

from scraper import pool_sizing

pool_sizing.concurrent_workers()  # before any app.* import -- see that module's docstring

from app.core.database import AsyncSessionLocal, engine, init_db  # noqa: E402
from app.core.scrape_lock import scrape_write_lock  # noqa: E402
from app.models.models import State, StateMonthCategoryFuelTotal  # noqa: E402
from app.services.scraper_service import persist_state_month_category_fuel_batch  # noqa: E402
from scraper.analytics_scraper import FUEL_VALUES, CaptchaSolveError, load_session, scrape_state_year, verify_tesseract  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("run_analytics_fuel_scrape")


async def _state_list(db) -> list[tuple[str, str]]:
    result = await db.execute(select(State.state_code, State.state_name))
    return result.all()


async def _already_done(db, year: int) -> set[tuple[str, str]]:
    query = select(distinct(StateMonthCategoryFuelTotal.state_code), StateMonthCategoryFuelTotal.fuel).where(
        StateMonthCategoryFuelTotal.year == year
    )
    result = await db.execute(query)
    return set(result.all())


async def _run_year(states: list[tuple[str, str]], year: int, concurrent: int, force: bool, tesseract_path: str) -> None:
    async with AsyncSessionLocal() as db:
        skip_pairs = frozenset() if force else await _already_done(db, year)
    if skip_pairs:
        logger.info("Resuming: %d state/fuel combos already scraped for %d", len(skip_pairs), year)

    sem = asyncio.Semaphore(concurrent)

    async def worker(state_code: str, state_name: str, fuel: str) -> None:
        # Same isolation as run_analytics_scrape.py's worker: own AsyncClient
        # (session-bound CAPTCHA), own AsyncSession, broad except so one bad
        # combo out of ~1,224/year doesn't abort the whole run.
        try:
            async with sem, httpx.AsyncClient(timeout=30) as client:
                csrf_token = await load_session(client)
                records = await scrape_state_year(client, tesseract_path, csrf_token, state_code, year, fuel=fuel)
            async with AsyncSessionLocal() as db:
                await persist_state_month_category_fuel_batch(db, state_code, state_name, year, fuel, records)
                await db.commit()
            logger.info("state=%s (%s) year=%d fuel=%s: %d rows", state_code, state_name, year, fuel, len(records))
        except CaptchaSolveError as e:
            logger.warning("state=%s year=%d fuel=%s: %s -- skipping", state_code, year, fuel, e)
        except Exception:
            logger.exception("state=%s year=%d fuel=%s: unexpected failure -- skipping", state_code, year, fuel)

    todo = [
        (code, name, fuel)
        for code, name in states
        for fuel in FUEL_VALUES
        if (code, fuel) not in skip_pairs
    ]
    await asyncio.gather(*(worker(code, name, fuel) for code, name, fuel in todo))


async def main(from_year: int, to_year: int, concurrent: int = 8, force: bool = False) -> None:
    logger.info("Starting analytics fuel scrape (years=%d-%d, concurrent=%d, force=%s) at %s",
                from_year, to_year, concurrent, force, datetime.now(timezone.utc))
    await init_db()
    tesseract_path = await verify_tesseract()

    async with AsyncSessionLocal() as db:
        states = await _state_list(db)

    for year in range(from_year, to_year + 1):
        lock_key = f"state_month_category_fuel_totals:{year}"
        try:
            async with scrape_write_lock(engine, lock_key):
                await _run_year(states, year, concurrent, force, tesseract_path)
        except Exception:
            logger.exception("year=%d: failed, moving to next year", year)

    logger.info("Analytics fuel scrape complete (years=%d-%d).", from_year, to_year)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, help="Scrape a single year")
    parser.add_argument("--from-year", type=int, help="Start of year range")
    parser.add_argument("--to-year", type=int, help="End of year range (inclusive)")
    # 6, not 8+ -- see run_analytics_scrape.py's note: benchmarked, local
    # tesseract OCR is the bottleneck, so higher concurrency buys no
    # throughput and only adds CAPTCHA retries.
    parser.add_argument("--concurrent", type=int, default=6, help="Concurrent state/fuel combos per year")
    parser.add_argument("--force", action="store_true", help="Re-scrape combos that already have data")
    args = parser.parse_args()

    if args.year is not None:
        from_year = to_year = args.year
    elif args.from_year is not None and args.to_year is not None:
        from_year, to_year = args.from_year, args.to_year
    else:
        parser.error("pass either --year or both --from-year and --to-year")

    asyncio.run(main(from_year, to_year, args.concurrent, args.force))
