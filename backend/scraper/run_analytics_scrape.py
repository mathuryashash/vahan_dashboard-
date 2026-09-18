"""Standalone entrypoint for the new analytics.parivahan.gov.in scraper --
state x month x vehicle-category totals. See analytics_scraper.py for the
site-interaction details (CAPTCHA solving, form shape, HTML parsing) this
just wires into a state/year loop, following run_crosstab_scrape.py's
lock-per-year + resume-by-natural-key pattern.

Usage: python -m scraper.run_analytics_scrape --from-year 2003 --to-year 2026 [--concurrent 4] [--force]
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
from app.models.models import State, StateMonthCategoryTotal  # noqa: E402
from app.services.scraper_service import persist_state_month_category_batch  # noqa: E402
from scraper.analytics_scraper import CaptchaSolveError, load_session, scrape_state_year, verify_tesseract  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("run_analytics_scrape")


async def _state_list(db) -> list[tuple[str, str]]:
    result = await db.execute(select(State.state_code, State.state_name))
    return result.all()


async def _already_done(db, year: int) -> set[str]:
    query = select(distinct(StateMonthCategoryTotal.state_code)).where(StateMonthCategoryTotal.year == year)
    result = await db.execute(query)
    return {row[0] for row in result.all()}


async def _run_year(states: list[tuple[str, str]], year: int, concurrent: int, force: bool, tesseract_path: str) -> None:
    async with AsyncSessionLocal() as db:
        skip_codes = frozenset() if force else await _already_done(db, year)
    if skip_codes:
        logger.info("Resuming: %d states already scraped for %d", len(skip_codes), year)

    sem = asyncio.Semaphore(concurrent)

    async def worker(state_code: str, state_name: str) -> None:
        # Each worker gets its own AsyncClient (session-bound CAPTCHA/cookies)
        # and its own AsyncSession (SQLAlchemy async sessions aren't safe to
        # share across concurrently-running coroutines).
        #
        # Broad `except Exception` (not just CaptchaSolveError) is deliberate:
        # this runs unattended for hours across ~36 states x many years, and
        # gather() has no return_exceptions=True, so one uncaught network
        # blip or parse error on any single state would otherwise kill every
        # remaining state and year in the run. Doesn't catch CancelledError
        # (a BaseException), so real shutdown/cancellation still works.
        try:
            async with sem, httpx.AsyncClient(timeout=30) as client:
                csrf_token = await load_session(client)
                records = await scrape_state_year(client, tesseract_path, csrf_token, state_code, year)
            async with AsyncSessionLocal() as db:
                await persist_state_month_category_batch(db, state_code, state_name, year, records)
                await db.commit()
            logger.info("state=%s (%s) year=%d: %d rows", state_code, state_name, year, len(records))
        except CaptchaSolveError as e:
            logger.warning("state=%s year=%d: %s -- skipping", state_code, year, e)
        except Exception:
            logger.exception("state=%s year=%d: unexpected failure -- skipping", state_code, year)

    todo = [(code, name) for code, name in states if code not in skip_codes]
    await asyncio.gather(*(worker(code, name) for code, name in todo))


async def main(from_year: int, to_year: int, concurrent: int = 4, force: bool = False) -> None:
    logger.info("Starting analytics scrape (years=%d-%d, concurrent=%d, force=%s) at %s",
                from_year, to_year, concurrent, force, datetime.now(timezone.utc))
    await init_db()
    tesseract_path = await verify_tesseract()

    async with AsyncSessionLocal() as db:
        states = await _state_list(db)

    for year in range(from_year, to_year + 1):
        lock_key = f"state_month_category_totals:{year}"
        try:
            async with scrape_write_lock(engine, lock_key):
                await _run_year(states, year, concurrent, force, tesseract_path)
        except Exception:
            # Lock contention (another process already scraping this year)
            # or a DB hiccup in _already_done shouldn't abort every other
            # year in a multi-year --from-year/--to-year range.
            logger.exception("year=%d: failed, moving to next year", year)

    logger.info("Analytics scrape complete (years=%d-%d).", from_year, to_year)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, help="Scrape a single year")
    parser.add_argument("--from-year", type=int, help="Start of year range")
    parser.add_argument("--to-year", type=int, help="End of year range (inclusive)")
    # 6, not 8+: benchmarked, the bottleneck is local tesseract OCR, not the
    # server. Concurrency 12 returned identical throughput to 6 (1.96
    # combos/s both) while raising requests per combo from 2.25 to 3.39 --
    # the extra requests are just CAPTCHA retries from OCR contention, so
    # higher settings hammer VAHAN harder for no gain.
    parser.add_argument("--concurrent", type=int, default=6, help="Concurrent states per year")
    parser.add_argument("--force", action="store_true", help="Re-scrape states that already have data")
    args = parser.parse_args()

    if args.year is not None:
        from_year = to_year = args.year
    elif args.from_year is not None and args.to_year is not None:
        from_year, to_year = args.from_year, args.to_year
    else:
        parser.error("pass either --year or both --from-year and --to-year")

    asyncio.run(main(from_year, to_year, args.concurrent, args.force))
