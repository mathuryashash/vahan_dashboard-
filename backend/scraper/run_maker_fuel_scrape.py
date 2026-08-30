"""Standalone entrypoint for the Maker x Fuel cross-tab scrape. Mirrors
run_maker_category_scrape.py exactly -- see
docs/superpowers/specs/2026-08-25-maker-category-crosstab-design.md.

Usage: python -m scraper.run_maker_fuel_scrape [--year YYYY] [--force]
"""
import argparse
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.database import AsyncSessionLocal, init_db
from app.models.models import MakerFuelTotal
from app.services.scraper_service import persist_maker_fuel_batch, _state_code_lookup
from scraper.vahan_scraper import scrape_all_india_maker_fuel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("run_maker_fuel_scrape")


async def _already_done_rtos(db, year: int) -> dict[str, frozenset[str]]:
    query = select(MakerFuelTotal.state_name, MakerFuelTotal.rto_code).where(
        MakerFuelTotal.year == year
    ).distinct()
    result = await db.execute(query)
    done: dict[str, set[str]] = {}
    for state_name, rto_code in result.all():
        done.setdefault(state_name, set()).add(rto_code)
    return {state_name: frozenset(codes) for state_name, codes in done.items()}


async def main(year: int, force: bool = False) -> None:
    logger.info(
        "Starting Maker x Fuel scrape (year=%s, force=%s) at %s",
        year, force, datetime.now(timezone.utc),
    )
    await init_db()

    async with AsyncSessionLocal() as db:
        state_codes = await _state_code_lookup(db)
        skip_rtos = {} if force else await _already_done_rtos(db, year)
        if skip_rtos:
            total_skipped = sum(len(v) for v in skip_rtos.values())
            logger.info("Resuming: %d RTOs across %d states already scraped this run", total_skipped, len(skip_rtos))

        rto_count = 0
        async for item in scrape_all_india_maker_fuel(year=year, skip_rtos=skip_rtos):
            if item.get("state_complete"):
                state_name = item["state_name"]
                total, skipped, succeeded = item["rto_total"], item["rto_skipped"], item["rto_succeeded"]
                logger.info("%s: %d/%d RTOs done (%d this run, %d earlier)", state_name, skipped + succeeded, total, succeeded, skipped)
                continue

            batch = item
            code = state_codes.get(batch["state_name"])
            if code is None:
                logger.warning("No state_code found for '%s', skipping batch", batch["state_name"])
                continue
            await persist_maker_fuel_batch(db, batch, state_code=code, year=year)
            await db.commit()
            rto_count += 1
            if rto_count % 25 == 0:
                logger.info("Scraped %d RTOs so far...", rto_count)

    logger.info("Maker x Fuel scrape complete (year=%s). %d RTOs processed.", year, rto_count)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=datetime.now().year)
    parser.add_argument("--force", action="store_true", help="Re-scrape every RTO even if it already has data")
    args = parser.parse_args()
    asyncio.run(main(args.year, args.force))
