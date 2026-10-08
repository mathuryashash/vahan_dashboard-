"""Phase A of the live-features replacement (scraper_review §4.4): answer
the "live" maker lookup, the fuel/category leaderboard and maker search from
tables we already hold, instead of scraping the government analytics site
(CAPTCHA + OCR) on every click.

| question                         | stored source                     | grain   |
|----------------------------------|-----------------------------------|---------|
| maker, no fuel, no category      | registrations canonical maker pass | monthly |
| maker, no fuel, category         | maker_category_totals              | yearly  |
| maker, fuel                      | maker_fuel_totals                  | yearly  |
| maker, fuel + category           | NOT answerable (mft has no category) |       |
| leaderboard, fuel                | maker_fuel_totals                  | yearly  |
| leaderboard, no fuel             | maker_category_totals              | yearly  |
| leaderboard, fuel + category     | NOT answerable                     |         |
| maker search                     | DISTINCT maker over registrations  | cached  |

Checked against the live cache (scraper_review §4.3): MH 2024 Honda 678,126
(live cache) vs 678,132 (registrations); Hero monthly identical ±1.

Yearly rows keep the live response shape {month, category, count} with
month=0 ("whole year") so callers that sum `records` still get the right
total; `grain` says which one it is. Unanswerable combinations return no
rows plus `unanswerable_reason` -- never an estimate (the membership-
approximation bug this codebase already paid for, see category_makers).

Scope: every query takes state_code (+ rto for RTO-tier accounts, + the
effective category) from the endpoint, which resolves them through the
usual scope dependencies -- this module never widens them.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.query_filters import category_makers
from app.models.models import MakerCategoryTotal, MakerFuelTotal, Registration
from app.services import data_freshness

GRAIN_MONTH = "month"
GRAIN_YEAR = "year"

FUEL_AND_CATEGORY_REASON = (
    "Maker x fuel x vehicle category is not held in our tables (maker_fuel_totals has no "
    "category axis), so this combination cannot be answered without estimating."
)


@dataclass
class StoredAnswer:
    records: list[dict] = field(default_factory=list)
    grain: str = GRAIN_MONTH
    unanswerable_reason: str | None = None


async def as_of(db: AsyncSession) -> str | None:
    """Date (YYYY-MM-DD, UTC) of the newest scrape in the data, or None."""
    fresh = await data_freshness.get_freshness(db)
    return fresh.last_scrape_at.date().isoformat() if fresh.last_scrape_at else None


async def maker_query(
    db: AsyncSession, state_code: str, year: int, maker: str,
    fuel: str | None = None, rto: str | None = None, category: str | None = None,
) -> StoredAnswer:
    maker = maker.strip().upper()
    fuel = fuel.strip().upper() if fuel else None
    if fuel and category:
        return StoredAnswer(grain=GRAIN_YEAR, unanswerable_reason=FUEL_AND_CATEGORY_REASON)

    if fuel:
        q = (
            select(MakerFuelTotal.fuel_type, func.sum(MakerFuelTotal.count))
            .where(MakerFuelTotal.state_code == state_code, MakerFuelTotal.year == year,
                   MakerFuelTotal.maker == maker, MakerFuelTotal.fuel_type == fuel)
            .group_by(MakerFuelTotal.fuel_type)
        )
        if rto:
            q = q.where(MakerFuelTotal.rto_code == rto)
        rows = (await db.execute(q)).all()
        return StoredAnswer(
            records=[{"month": 0, "category": f, "count": int(c)} for f, c in rows if c],
            grain=GRAIN_YEAR,
        )

    if category:
        q = (
            select(MakerCategoryTotal.vehicle_class, func.sum(MakerCategoryTotal.count))
            .where(MakerCategoryTotal.state_code == state_code, MakerCategoryTotal.year == year,
                   MakerCategoryTotal.maker == maker, MakerCategoryTotal.vehicle_category == category)
            .group_by(MakerCategoryTotal.vehicle_class)
            .order_by(MakerCategoryTotal.vehicle_class)
        )
        if rto:
            q = q.where(MakerCategoryTotal.rto_code == rto)
        rows = (await db.execute(q)).all()
        return StoredAnswer(
            records=[{"month": 0, "category": vc, "count": int(c)} for vc, c in rows if c],
            grain=GRAIN_YEAR,
        )

    # Canonical maker pass only (is_supplementary NOT TRUE, vehicle_class
    # 'All'): the class/fuel passes would double-count.
    q = (
        select(Registration.month, func.sum(Registration.count))
        .where(Registration.state_code == state_code, Registration.year == year,
               Registration.maker == maker, Registration.is_supplementary.isnot(True))
        .group_by(Registration.month)
        .order_by(Registration.month)
    )
    if rto:
        q = q.where(Registration.rto_code == rto)
    rows = (await db.execute(q)).all()
    return StoredAnswer(
        records=[{"month": int(m), "category": "ALL", "count": int(c)} for m, c in rows if c],
        grain=GRAIN_MONTH,
    )


async def leaderboard(
    db: AsyncSession, state_code: str, year: int, fuel: str | None = None, limit: int = 10,
    category: str | None = None, rto: str | None = None,
) -> StoredAnswer:
    """Top makers by stored yearly volume; `records` is [{maker, total}]."""
    fuel = fuel.strip().upper() if fuel else None
    if fuel and category:
        return StoredAnswer(grain=GRAIN_YEAR, unanswerable_reason=FUEL_AND_CATEGORY_REASON)
    model = MakerFuelTotal if fuel else MakerCategoryTotal
    total = func.sum(model.count)
    q = select(model.maker, total).where(model.state_code == state_code, model.year == year)
    if fuel:
        q = q.where(MakerFuelTotal.fuel_type == fuel)
    if category:
        q = q.where(MakerCategoryTotal.vehicle_category == category)
    if rto:
        q = q.where(model.rto_code == rto)
    rows = (await db.execute(q.group_by(model.maker).order_by(total.desc(), model.maker).limit(limit))).all()
    return StoredAnswer(
        records=[{"maker": m, "total": int(t)} for m, t in rows if t],
        grain=GRAIN_YEAR,
    )


# ---- maker search -----------------------------------------------------------

_MAKER_LIST_TTL = 3600.0
_maker_list: tuple[float, list[str]] | None = None
_maker_list_lock = asyncio.Lock()

# Recursive "loose index scan" over idx_reg_year_maker_count: one index probe
# per distinct maker instead of reading every registrations row. Measured on
# prod: 7,326 makers in 591 ms vs 1,627 ms for COUNT(DISTINCT) on mct.
_DISTINCT_MAKERS_SQL = text("""
WITH RECURSIVE m AS (
    (SELECT maker FROM registrations WHERE maker IS NOT NULL ORDER BY maker LIMIT 1)
    UNION ALL
    SELECT (SELECT r.maker FROM registrations r WHERE r.maker > m.maker ORDER BY r.maker LIMIT 1)
    FROM m WHERE m.maker IS NOT NULL
)
SELECT maker FROM m WHERE maker IS NOT NULL
""")


async def distinct_makers(db: AsyncSession) -> list[str]:
    """Every maker name we hold (all years), cached for an hour. Cleared by
    TTLCache.clear_all()'s post-scrape hook via reset_maker_list()."""
    global _maker_list
    now = time.monotonic()
    if _maker_list and now - _maker_list[0] < _MAKER_LIST_TTL:
        return _maker_list[1]
    async with _maker_list_lock:
        if _maker_list and time.monotonic() - _maker_list[0] < _MAKER_LIST_TTL:
            return _maker_list[1]
        names = [r[0] for r in (await db.execute(_DISTINCT_MAKERS_SQL)).all()]
        _maker_list = (time.monotonic(), names)
        return names


def reset_maker_list() -> None:
    global _maker_list
    _maker_list = None


async def search_makers(db: AsyncSession, q: str, limit: int = 20, category: str | None = None) -> list[str]:
    """Case-insensitive substring match over our own maker vocabulary
    (prefix matches first, then alphabetical), clamped to the category's
    makers for category-scoped callers -- the same rule the live search used."""
    needle = q.strip().upper()
    if not needle:
        return []
    names = await distinct_makers(db)
    hits = [n for n in names if needle in n]
    if category:
        allowed = set((await db.execute(category_makers(category))).scalars().all())
        hits = [n for n in hits if n in allowed]
    hits.sort(key=lambda n: (not n.startswith(needle), n))
    return hits[:limit]
