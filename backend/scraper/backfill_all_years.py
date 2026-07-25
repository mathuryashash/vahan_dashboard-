"""Backfill real scraped data for every year the live VAHAN4 site offers
(2003-2026), across all three dimensions.

Runs one year at a time -- maker, vehicle_class, and fuel concurrently for
that year (same approach as app.services.scraper_service.run_scraper, just
looped across years) -- rather than firing every year at once, which would
mean dozens of concurrent sessions hitting the government site and a much
higher chance of tripping its bot detection. Fully resumable: interrupting
and re-running just resumes mid-year (per-RTO tracking, see
run_full_scrape._already_done_rtos) or moves to the next year in the list.

Usage: python -m scraper.backfill_all_years [--start-year 2025] [--end-year 2003]
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


async def _run_dimension_with_retries(year: int, dimension: str) -> None:
    """scrape_year_dimension resumes from the last completed RTO on every
    call (main() re-queries the DB for already-done RTOs at the top), so
    retrying a failed dimension is just calling it again -- no separate
    checkpoint bookkeeping needed here."""
    for attempt in range(DIMENSION_RETRIES):
        try:
            await scrape_year_dimension(year, dimension)
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


async def run_year(year: int) -> None:
    logger.info("=== Starting year %s (maker, vehicle_class, fuel concurrently) ===", year)
    results = await asyncio.gather(
        *(_run_dimension_with_retries(year, dimension) for dimension in sorted(DIMENSIONS)),
        return_exceptions=True,
    )
    for dimension, result in zip(sorted(DIMENSIONS), results):
        if isinstance(result, Exception):
            logger.error("Year %s / %s failed after %d attempts: %s", year, dimension, DIMENSION_RETRIES, result)
    logger.info("=== Year %s done ===", year)


async def main(start_year: int, end_year: int) -> None:
    step = -1 if start_year >= end_year else 1
    years = list(range(start_year, end_year + step, step))
    logger.info("Backfill plan: %d years, newest to oldest: %s", len(years), years)
    for year in years:
        await run_year(year)
    logger.info("Backfill complete: %s", datetime.now())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-year", type=int, default=2025)
    parser.add_argument("--end-year", type=int, default=2003)
    args = parser.parse_args()
    asyncio.run(main(args.start_year, args.end_year))
