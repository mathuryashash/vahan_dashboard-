"""Targeted re-scrape of RTOs whose rows for a given year contain
stale-page duplicates -- despite the filename (kept for continuity with
existing usage/history), this now takes --year and works for any year, not
just 2026. Originally written to clean up 2026 specifically; generalized
after the same duplicate-row pattern was confirmed present in 2024 (84
dirty RTOs) and 2025 (70 dirty RTOs) too, via the same detection query.

Reuses scrape_all_india's own resume machinery, inverted: skip_rtos normally
means "don't redo these"; here we build it as "every KNOWN rto for this
dimension EXCEPT the dirty ones", so only dirty RTOs get scraped. Each
scraped batch goes through persist_rto_batch's scoped delete-then-insert,
so dirty rows are fully replaced, not appended to.

Usage: python cleanup_dups_2026.py <dimension> [--year YYYY]
       dimension: maker | vehicle_class | fuel
       --year: defaults to 2026
"""
import argparse
import asyncio
import logging

import asyncpg
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.services.scraper_service import persist_rto_batch
from scraper.vahan_scraper import REQUEST_DELAY_SECONDS, scrape_all_india

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("cleanup_dups")

PG_DSN = "postgresql://vahan:vahan@localhost:5432/vahan"

# Same dimension filters used by run_full_scrape._already_done_rtos --
# keeps "which rows belong to this dimension" consistent everywhere.
DIM_FILTERS = {
    "maker": "is_supplementary=false AND vehicle_class='All'",
    "vehicle_class": "is_supplementary=true AND fuel_type IS NULL",
    "fuel": "is_supplementary=true AND fuel_type IS NOT NULL",
}
DIM_LABEL_COL = {"maker": "maker", "vehicle_class": "vehicle_class", "fuel": "fuel_type"}


async def fetch_dirty_and_known(dsn: str, dimension: str, year: int):
    """Returns ({state_name: frozenset(dirty_rto_codes)},
                {state_name: frozenset(all_known_rto_codes)})."""
    dim_filter = DIM_FILTERS[dimension]
    label_col = DIM_LABEL_COL[dimension]
    conn = await asyncpg.connect(dsn, timeout=15)
    try:
        dirty_rows = await conn.fetch(
            f"""
            SELECT DISTINCT rto_code, state_name FROM registrations
            WHERE year=$1 AND {dim_filter} AND rto_code IN (
                SELECT rto_code FROM registrations
                WHERE year=$1 AND {dim_filter}
                GROUP BY rto_code, year, month, {label_col}
                HAVING COUNT(*) > 1
            )
            """,
            year,
        )
        known_rows = await conn.fetch(
            f"""
            SELECT DISTINCT rto_code, state_name FROM registrations
            WHERE year=$1 AND {dim_filter}
            """,
            year,
        )
    finally:
        await conn.close()

    dirty: dict[str, set] = {}
    known: dict[str, set] = {}
    for r in dirty_rows:
        dirty.setdefault(r["state_name"], set()).add(r["rto_code"])
    for r in known_rows:
        known.setdefault(r["state_name"], set()).add(r["rto_code"])
    return (
        {s: frozenset(c) for s, c in dirty.items()},
        {s: frozenset(c) for s, c in known.items()},
    )


async def main(dimension: str, year: int) -> None:
    dirty, known = await fetch_dirty_and_known(PG_DSN, dimension, year)
    total_dirty = sum(len(v) for v in dirty.values())
    logger.info("Dirty RTOs for %s/%d: %d across %d states", dimension, year, total_dirty, len(dirty))
    if not dirty:
        logger.info("Nothing to do.")
        return

    # Invert: skip every known-clean RTO; scrape only the dirty ones.
    # Build entries for ALL known states -- a state absent from skip_rtos
    # gets an empty already-done set in scrape_all_india and would be
    # fully re-scraped, which is exactly the bug this line-up avoids.
    all_states = set(known) | set(dirty)
    skip_rtos = {
        state: frozenset(known.get(state, frozenset()) - dirty.get(state, frozenset()))
        for state in all_states
    }

    from collections import Counter

    from sqlalchemy import select

    from app.models.models import State

    async def _batch_is_clean(records: list[dict]) -> bool:
        """Reject ANY batch containing duplicate (label, month) pairs.
        Catches every duplication mechanism -- multi-page replays included --
        regardless of what slipped past the scraper's own stale-page detector."""
        pairs = Counter((r["label"], r["month"]) for r in records)
        return all(n == 1 for n in pairs.values())

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(State.state_name, State.state_code))
        state_codes = {name: code for name, code in result.all()}
        scraped = 0
        rejected = 0
        async for item in scrape_all_india(
            year=year,
            dimension=dimension,
            # Double the normal per-RTO delay for this recovery pass: the
            # last maker run hit stale-page-stuck on ~35% of RTOs (vs. ~3%
            # seen testing vehicle_class in isolation) and eventually a
            # ViewExpiredException too -- consistent with VAHAN throttling a
            # session that's been under sustained continuous load for
            # hours. Slower and reliable beats fast and mostly-corrupted.
            delay_seconds=REQUEST_DELAY_SECONDS * 2,
            skip_rtos=skip_rtos,
            max_concurrent_states=1,
        ):
            if item.get("state_complete"):
                logger.info(
                    "%s: %d/%d RTOs done (%d this run)",
                    item["state_name"],
                    item["rto_skipped"] + item["rto_succeeded"],
                    item["rto_total"],
                    item["rto_succeeded"],
                )
                continue
            if not await _batch_is_clean(item["records"]):
                rejected += 1
                logger.warning(
                    "REJECTED %s / %s: batch contains duplicate (label, month) "
                    "pairs -- not persisting; will retry on a later pass",
                    item["state_name"],
                    item["rto_code"],
                )
                continue
            code = state_codes.get(item["state_name"])
            if code is None:
                logger.warning("No state_code for '%s', skipping batch", item["state_name"])
                continue
            await persist_rto_batch(db, item, state_code=code, dimension=dimension)
            await db.commit()
            scraped += 1

            # Post-write proof: immediately re-query THIS rto and confirm the
            # persisted rows are duplicate-free. Catches any mechanism (double
            # yield, partial delete, whatever) that survives upstream checks.
            rows_result = await db.execute(
                text(
                    "SELECT COUNT(*) FROM registrations WHERE rto_code=:r "
                    "AND year=:y AND " + DIM_FILTERS[dimension]
                ),
                {"r": item["rto_code"], "y": year},
            )
            n_rows = rows_result.scalar()
            label_col = DIM_LABEL_COL[dimension]
            pairs_result = await db.execute(
                text(
                    f"SELECT COUNT(*) FROM (SELECT {label_col}, month FROM registrations "
                    "WHERE rto_code=:r AND year=:y AND " + DIM_FILTERS[dimension] +
                    " GROUP BY " + label_col + ", month) x"
                ),
                {"r": item["rto_code"], "y": year},
            )
            n_pairs = pairs_result.scalar()
            logger.info(
                "WROTE %s / %s: %d records -> %d rows, %d unique pairs%s",
                item["state_name"],
                item["rto_code"],
                len(item["records"]),
                n_rows,
                n_pairs,
                "" if n_rows == n_pairs else "  *** STILL DIRTY AFTER WRITE ***",
            )
            if scraped % 25 == 0:
                logger.info("Re-scraped %d/%d dirty RTOs...", scraped, total_dirty)
        logger.info(
            "Cleanup done: %d RTOs re-scraped, %d batches REJECTED for %s/%d",
            scraped,
            rejected,
            dimension,
            year,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("dimension", choices=sorted(DIM_FILTERS))
    parser.add_argument("--year", type=int, default=2026)
    args = parser.parse_args()
    asyncio.run(main(args.dimension, args.year))
