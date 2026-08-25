"""Backfill real scraped data for every year the live VAHAN4 site offers
(2003-2026), across all three dimensions.

Runs one year at a time -- maker, vehicle_class, and fuel concurrently for
that year (same approach as app.services.scraper_service.run_scraper, just
looped across years) -- rather than firing every year at once, which would
mean dozens of concurrent sessions hitting the government site and a much
higher chance of tripping its bot detection. Fully resumable: interrupting
and re-running just resumes mid-year (per-RTO tracking, see
run_full_scrape._already_done_rtos) or moves to the next year in the list.

Usage: python -m scraper.backfill_all_years [--start-year 2025] [--end-year 2003] [--concurrent-states N]
"""
import argparse
import asyncio
import logging
from datetime import datetime

from scraper.run_full_scrape import main as scrape_year_dimension
from scraper.vahan_scraper import DIMENSIONS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_all_years")


DIMENSION_RETRIES = 3
DIMENSION_RETRY_BASE_DELAY = 30  # seconds, doubled each attempt

CONCURRENT_STATES = 1  # Can be overridden via CLI


async def _run_dimension_with_retries(year: int, dimension: str, concurrent_states: int = CONCURRENT_STATES, force: bool = False) -> None:
    """scrape_year_dimension resumes from the last completed RTO on every
    call (main() re-queries the DB for already-done RTOs at the top), so
    retrying a failed dimension is just calling it again -- no separate
    checkpoint bookkeeping needed here."""
    for attempt in range(DIMENSION_RETRIES):
        try:
            await scrape_year_dimension(year, dimension, concurrent_states, force)
            return
        except Exception as exc:
            if attempt == DIMENSION_RETRIES - 1:
                raise
            delay = DIMENSION_RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning(
                "Year %s / %s failed (attempt %d/%d): %s -- retrying in %ds",
                year, dimension, attempt + 1, DIMENSION_RETRIES, exc, delay,
            )
            await asyncio.sleep(delay)


async def run_year(year: int, concurrent_states: int = CONCURRENT_STATES, force: bool = False) -> None:
    logger.info("=== Starting year %s (maker, vehicle_class, fuel concurrently) ===", year)
    results = await asyncio.gather(
        *(_run_dimension_with_retries(year, dimension, concurrent_states, force) for dimension in sorted(DIMENSIONS)),
        return_exceptions=True,
    )
    for dimension, result in zip(sorted(DIMENSIONS), results):
        if isinstance(result, Exception):
            logger.error("Year %s / %s failed after %d attempts: %s", year, dimension, DIMENSION_RETRIES, result)
    logger.info("=== Year %s done ===", year)


async def main(start_year: int, end_year: int, concurrent_states: int = CONCURRENT_STATES, force: bool = False) -> None:
    step = -1 if start_year >= end_year else 1
    years = list(range(start_year, end_year + step, step))
    logger.info("Backfill plan: %d years, newest to oldest: %s (force=%s)", len(years), years, force)
    for year in years:
        await run_year(year, concurrent_states, force)
    logger.info("Backfill complete: %s", datetime.now())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-year", type=int, default=2025)
    parser.add_argument("--end-year", type=int, default=2003)
    parser.add_argument("--concurrent-states", type=int, default=1, help="Number of states to scrape in parallel per dimension (default: 1)")
    parser.add_argument("--force", action="store_true", help="Re-scrape every RTO even if it already has data, instead of only resuming an interrupted run")
    args = parser.parse_args()
    asyncio.run(main(args.start_year, args.end_year, args.concurrent_states, args.force))
