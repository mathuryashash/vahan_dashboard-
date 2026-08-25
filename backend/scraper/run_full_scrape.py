"""Standalone entrypoint for a full-India live scrape. Run as its own OS process
(never as an in-process asyncio task inside the FastAPI/uvicorn server) — Playwright's
Chromium subprocess was observed to crash reliably within seconds when driven from a
background task sharing uvicorn's event loop, but runs cleanly as an independent process.
See app.services.scraper_service.run_scraper(), which launches this via subprocess.

Usage: python -m scraper.run_full_scrape [--year YYYY] [--dimension maker|vehicle_class|fuel] [--concurrent-states N]

The live site can only pivot on one dimension per RTO visit (see
scraper/vahan_scraper.py's DIMENSIONS), so getting maker + vehicle-class + fuel
breakdowns for a year means running this three times with different
--dimension values. Each run is independently resumable.
"""
import argparse
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal, init_db
from app.models.models import Registration
from app.services.scraper_service import persist_rto_batch, _state_code_lookup
from scraper.vahan_scraper import DIMENSIONS, scrape_all_india

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("run_full_scrape")


async def _already_done_rtos(db, year: int, dimension: str) -> dict[str, frozenset[str]]:
    """{state_name: {rto_code, ...}} for RTOs that already have real data for
    this exact (year, dimension) from a previous — possibly interrupted — run.
    Tracked per-RTO so resuming makes forward progress within a large state
    instead of restarting it from its first RTO every time the process gets
    cut off.

    The three dimensions are told apart by is_supplementary + fuel_type,
    matching exactly how persist_rto_batch writes them:
      - maker:         is_supplementary=False, vehicle_class='All'
      - vehicle_class:  is_supplementary=True,  fuel_type=NULL
      - fuel:           is_supplementary=True,  fuel_type IS NOT NULL
    Synthetic seed rows never set is_supplementary=True, so they can never be
    mistaken for a supplementary-dimension pass; the maker check additionally
    requires vehicle_class='All', which synthetic data never uses either.
    """
    query = select(Registration.state_name, Registration.rto_code).where(Registration.year == year).distinct()
    if dimension == "maker":
        query = query.where(Registration.vehicle_class == "All", Registration.is_supplementary.is_(False))
    elif dimension == "vehicle_class":
        query = query.where(Registration.is_supplementary.is_(True), Registration.fuel_type.is_(None))
    elif dimension == "fuel":
        query = query.where(Registration.is_supplementary.is_(True), Registration.fuel_type.isnot(None))
    else:
        raise ValueError(f"Unknown dimension: {dimension!r}")

    result = await db.execute(query)
    done: dict[str, set[str]] = {}
    for state_name, rto_code in result.all():
        done.setdefault(state_name, set()).add(rto_code)
    return {state_name: frozenset(codes) for state_name, codes in done.items()}


async def _purge_synthetic_for_state(db, state_name: str, year: int) -> int:
    """Real *maker-pass* rows always have vehicle_class='All' (see
    persist_rto_batch); the synthetic seed data is broken out by specific
    vehicle class. That's a reliable way to delete only the leftover
    synthetic rows for a state without touching the real maker data we just
    wrote -- PROVIDED it also excludes real vehicle_class-dimension rows,
    which legitimately have vehicle_class != 'All' too (that's the real class
    label, not a placeholder). Without the is_supplementary filter below,
    this deleted the real vehicle_class breakdown for a state the moment its
    maker pass next completed, silently wiping data that a vehicle_class scrape
    had already populated (fuel-dimension rows were unaffected only because
    they store vehicle_class='All', keeping the fuel breakdown in a separate
    column).

    Scoped to `year`: the scraper only ever targets one year at a time, so
    only that year's synthetic rows should be removed. An earlier version of
    this function had no year filter and deleted a state's ENTIRE synthetic
    history (all years) the moment its current-year data finished scraping —
    wiping out 2024/2025 placeholder data that the scraper never touched and
    had no replacement for.

    Only ever called for the 'maker' pass (see main()): that's the one whose
    real data is meant to fully replace synthetic fallback data for a state.
    The vehicle_class/fuel passes are purely additive breakdowns of numbers
    already established by the maker pass -- they never trigger a purge.
    """
    result = await db.execute(
        delete(Registration).where(
            Registration.state_name == state_name,
            Registration.vehicle_class != "All",
            Registration.year == year,
            Registration.is_supplementary.is_(False),
        )
    )
    return result.rowcount or 0


async def main(year: int, dimension: str, concurrent_states: int = 1, force: bool = False) -> None:
    logger.info(
        "Starting live VAHAN4 scrape (year=%s, dimension=%s, concurrent_states=%s, force=%s) at %s",
        year, dimension, concurrent_states, force, datetime.now(timezone.utc),
    )
    await init_db()  # ensures is_supplementary column exists; this script doesn't go through app.main's lifespan

    async with AsyncSessionLocal() as db:
        state_codes = await _state_code_lookup(db)
        # force=True re-scrapes every RTO regardless of existing data -- for
        # refreshing stale numbers, not just resuming an interrupted run.
        # _already_done_rtos can't tell "already has data from an interrupted
        # attempt of *this* run" apart from "already has data from a normal
        # scrape weeks ago"; without force, a full re-scrape intended to
        # correct stale numbers silently skips almost every RTO instead.
        skip_rtos = {} if force else await _already_done_rtos(db, year, dimension)
        if skip_rtos:
            total_skipped = sum(len(v) for v in skip_rtos.values())
            logger.info("Resuming: %d RTOs across %d states already scraped this run", total_skipped, len(skip_rtos))

        rto_count = 0
        states_replaced = 0
        states_partial = 0
        async for item in scrape_all_india(year=year, dimension=dimension, skip_rtos=skip_rtos, max_concurrent_states=concurrent_states):
            if item.get("state_complete"):
                state_name = item["state_name"]
                total, skipped, succeeded = item["rto_total"], item["rto_skipped"], item["rto_succeeded"]
                done_now = skipped + succeeded
                # Only purge on the maker pass -- see _purge_synthetic_for_state
                # docstring. vehicle_class/fuel passes are additive and never
                # touch the synthetic fallback data.
                if dimension == "maker" and total > 0 and done_now == total:
                    purged = await _purge_synthetic_for_state(db, state_name, year)
                    await db.commit()
                    states_replaced += 1
                    logger.info(
                        "%s: %d/%d RTOs done (%d this run, %d earlier) -- purged %d leftover synthetic rows",
                        state_name, done_now, total, succeeded, skipped, purged,
                    )
                elif total > 0 and done_now == total:
                    states_replaced += 1
                    logger.info("%s: %d/%d RTOs done (%d this run, %d earlier)", state_name, done_now, total, succeeded, skipped)
                else:
                    states_partial += 1
                    logger.warning(
                        "%s: only %d/%d RTOs done so far -- will resume this state next run",
                        state_name, done_now, total,
                    )
                continue

            batch = item
            code = state_codes.get(batch["state_name"])
            if code is None:
                logger.warning("No state_code found for '%s', skipping batch", batch["state_name"])
                continue
            await persist_rto_batch(db, batch, state_code=code, dimension=dimension)
            await db.commit()
            rto_count += 1
            if rto_count % 25 == 0:
                logger.info("Scraped %d RTOs so far...", rto_count)

    logger.info(
        "Live VAHAN4 scrape complete (year=%s, dimension=%s). %d RTOs processed, %d states fully done, %d states left for next run.",
        year, dimension, rto_count, states_replaced, states_partial,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=datetime.now().year)
    parser.add_argument("--dimension", choices=sorted(DIMENSIONS), default="maker")
    parser.add_argument("--concurrent-states", type=int, default=1, help="Number of states to scrape in parallel (default: 1)")
    parser.add_argument("--force", action="store_true", help="Re-scrape every RTO even if it already has data (vs. only resuming an interrupted run)")
    args = parser.parse_args()
    asyncio.run(main(args.year, args.dimension, args.concurrent_states, args.force))
