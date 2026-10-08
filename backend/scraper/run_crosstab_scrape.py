"""Standalone entrypoint for the 3 crosstab scrapes (Maker x Vehicle Class,
Maker x Fuel, Fuel x Vehicle Class) -- one parameterized script instead of
three that only ever differed in which model/persist-fn/scraper-fn they
wired together (confirmed identical otherwise; a bugfix to the shared logic
used to mean editing all three by hand). Each pivot is a genuinely different
shape from Registration (no month column, no is_supplementary concept) -- see
docs/superpowers/specs/2026-08-25-maker-category-crosstab-design.md.

Usage: python -m scraper.run_crosstab_scrape --dimension maker_category [--year YYYY] [--force]
"""
import argparse
import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable

from scraper import pool_sizing

pool_sizing.serial()  # before any app.* import -- see that module's docstring

from sqlalchemy import select  # noqa: E402

from app.core.database import AsyncSessionLocal, engine, init_db  # noqa: E402
from app.core.scrape_lock import exit_if_run_lock_busy, scrape_run_lock, scrape_write_lock  # noqa: E402
from app.models.models import FuelCategoryTotal, MakerCategoryTotal, MakerFuelTotal  # noqa: E402
from app.services.scraper_service import (  # noqa: E402
    _state_code_lookup, persist_fuel_category_batch, persist_maker_category_batch, persist_maker_fuel_batch,
)
from scraper.vahan_scraper import (  # noqa: E402
    scrape_all_india_fuel_category, scrape_all_india_maker_category, scrape_all_india_maker_fuel,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("run_crosstab_scrape")


@dataclass(frozen=True)
class _Dimension:
    label: str
    model: type
    persist: Callable[..., Awaitable[None]]
    scrape: Callable[..., object]


_DIMENSIONS: dict[str, _Dimension] = {
    "maker_category": _Dimension(
        "Maker x Vehicle Class", MakerCategoryTotal, persist_maker_category_batch, scrape_all_india_maker_category,
    ),
    "maker_fuel": _Dimension(
        "Maker x Fuel", MakerFuelTotal, persist_maker_fuel_batch, scrape_all_india_maker_fuel,
    ),
    "fuel_category": _Dimension(
        "Fuel x Vehicle Class", FuelCategoryTotal, persist_fuel_category_batch, scrape_all_india_fuel_category,
    ),
}


async def _already_done_rtos(db, model, year: int) -> dict[str, frozenset[str]]:
    query = select(model.state_name, model.rto_code).where(model.year == year).distinct()
    result = await db.execute(query)
    done: dict[str, set[str]] = {}
    for state_name, rto_code in result.all():
        done.setdefault(state_name, set()).add(rto_code)
    return {state_name: frozenset(codes) for state_name, codes in done.items()}


async def main(dimension: str, year: int, force: bool = False,
               only_rtos: dict[str, frozenset[str]] | None = None) -> None:
    async with scrape_run_lock(engine, f"run_crosstab_scrape {dimension} {year}"):
        await _main(dimension, year, force or only_rtos is not None, only_rtos)


async def _main(dimension: str, year: int, force: bool, only_rtos: dict[str, frozenset[str]] | None,
                take_write_lock: bool = True) -> int:
    """Returns RTOs persisted. take_write_lock=False only for a caller that
    already holds `<table>:<year>` itself and runs several RTO partitions of
    the same table-year concurrently (scraper.run_targeted_scrape)."""
    dim = _DIMENSIONS[dimension]
    logger.info("Starting %s scrape (year=%s, force=%s) at %s", dim.label, year, force, datetime.now(timezone.utc))
    await init_db()

    lock_key = f"{dim.model.__tablename__}:{year}"
    write_lock = scrape_write_lock(engine, lock_key) if take_write_lock else contextlib.nullcontext()
    async with write_lock, AsyncSessionLocal() as db:
        state_codes = await _state_code_lookup(db)
        skip_rtos = {} if force else await _already_done_rtos(db, dim.model, year)
        if skip_rtos:
            total_skipped = sum(len(v) for v in skip_rtos.values())
            logger.info("Resuming: %d RTOs across %d states already scraped this run", total_skipped, len(skip_rtos))

        rto_count = 0
        extra = {} if only_rtos is None else {"only_rtos": only_rtos}
        async for item in dim.scrape(year=year, skip_rtos=skip_rtos, **extra):
            if item.get("state_complete"):
                state_name = item["state_name"]
                total, skipped, succeeded = item["rto_total"], item["rto_skipped"], item["rto_succeeded"]
                logger.info("%s: %d/%d RTOs done (%d this run, %d earlier)", state_name, skipped + succeeded, total, succeeded, skipped)
                continue

            batch = item
            if not batch["records"]:
                # persist_* is delete-then-insert: an empty answer would wipe
                # the RTO-year's existing rows with nothing to replace them.
                # Empty is not evidence (see vahan_scraper._scrape_state).
                logger.warning("%s / %s: empty answer -- existing rows kept", batch["state_name"], batch["rto_code"])
                continue
            code = state_codes.get(batch["state_name"])
            if code is None:
                logger.warning("No state_code found for '%s', skipping batch", batch["state_name"])
                continue
            await dim.persist(db, batch, state_code=code, year=year)
            await db.commit()
            rto_count += 1
            if rto_count % 25 == 0:
                logger.info("Scraped %d RTOs so far...", rto_count)

    logger.info("%s scrape complete (year=%s). %d RTOs processed.", dim.label, year, rto_count)
    return rto_count


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dimension", choices=sorted(_DIMENSIONS), required=True)
    parser.add_argument("--year", type=int, default=datetime.now().year)
    parser.add_argument("--force", action="store_true", help="Re-scrape every RTO even if it already has data")
    args = parser.parse_args()
    try:
        asyncio.run(main(args.dimension, args.year, args.force))
    except Exception as exc:  # a busy run lock exits 4 with a message; anything else re-raises
        exit_if_run_lock_busy(exc)
