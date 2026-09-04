"""Cross-dimension consistency check: the maker, vehicle_class, and fuel
passes are three independent live scrapes of the SAME underlying
registrations for a given (RTO, month) -- see Registration.is_supplementary
-- so their totals should agree. A cell where two passes disagree by more
than MAX_PCT_DIFF means one of them scraped stale or corrupted data for
that RTO/month; this doesn't say which one, just that something's off.

Distinct from the live-vs-VAHAN check (backend/_live_compare.py, manual/
one-RTO-at-a-time): this is a fast, DB-only internal consistency check
across data already scraped, run after every full scrape cycle (see
scraper_service.run_scraper).
"""
import logging

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Registration, ScrapeQualityLog

logger = logging.getLogger("scrape_quality")

MAX_PCT_DIFF = 2.0


async def _totals_by_rto_month(db: AsyncSession, year: int, is_supplementary: bool, fuel_is_null: bool | None):
    query = select(
        Registration.rto_code, Registration.state_name, Registration.month,
        func.sum(Registration.count).label("total"),
    ).where(Registration.year == year, Registration.is_supplementary.is_(is_supplementary))
    if fuel_is_null is True:
        query = query.where(Registration.fuel_type.is_(None))
    elif fuel_is_null is False:
        query = query.where(Registration.fuel_type.isnot(None))
    query = query.group_by(Registration.rto_code, Registration.state_name, Registration.month)
    result = await db.execute(query)
    return {(row.rto_code, row.month): (row.state_name, row.total) for row in result.all()}


async def check_scrape_quality(db: AsyncSession, year: int) -> dict:
    """Computes per-(rto_code, month) agreement across the 3 dimension
    passes for `year`, replaces that year's ScrapeQualityLog rows with the
    fresh results, and returns a summary dict. Cells where fewer than 2 of
    the 3 dimensions have any data at all are skipped (nothing to compare --
    that's a coverage gap, not a disagreement; Priority 1's dirty-row
    cleanup is the tool for actual missing/duplicate scrape data)."""
    maker_totals = await _totals_by_rto_month(db, year, False, None)
    vclass_totals = await _totals_by_rto_month(db, year, True, True)
    fuel_totals = await _totals_by_rto_month(db, year, True, False)

    keys = set(maker_totals) | set(vclass_totals) | set(fuel_totals)
    rows_to_insert = []
    checked = 0
    clean = 0
    for key in keys:
        rto_code, month = key
        present = [d[key] for d in (maker_totals, vclass_totals, fuel_totals) if key in d]
        if len(present) < 2:
            continue
        state_name = present[0][0]
        values = [v for _, v in present]
        mx, mn = max(values), min(values)
        pct_diff = ((mx - mn) / mx * 100) if mx > 0 else 0.0
        is_clean = pct_diff <= MAX_PCT_DIFF
        checked += 1
        if is_clean:
            clean += 1
        rows_to_insert.append(ScrapeQualityLog(
            rto_code=rto_code, state_name=state_name, year=year, month=month,
            maker_total=maker_totals.get(key, (None, 0))[1],
            vehicle_class_total=vclass_totals.get(key, (None, 0))[1],
            fuel_total=fuel_totals.get(key, (None, 0))[1],
            max_pct_diff=round(pct_diff, 2),
            is_clean=is_clean,
        ))

    await db.execute(delete(ScrapeQualityLog).where(ScrapeQualityLog.year == year))
    db.add_all(rows_to_insert)
    await db.commit()

    summary = {
        "year": year,
        "cells_checked": checked,
        "cells_clean": clean,
        "pct_clean": round(clean / checked * 100, 1) if checked else None,
    }
    logger.info(
        "Scrape quality check for %d: %d/%d cells clean (%.1f%%, threshold %.0f%% diff)",
        year, clean, checked, summary["pct_clean"] or 0.0, MAX_PCT_DIFF,
    )
    return summary
