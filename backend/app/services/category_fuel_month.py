"""Real month-level Category x Powertrain numbers, where the stored data
honestly has them.

Overview with Category + Powertrain + Month used to show the calendar-year
total from fuel_category_totals (no month axis) plus two modelled "~"
estimates. A monthly source does exist: state_month_category_fuel_totals
(analytics portal: state x month x portal category x raw fuel). Its category
axis is the PORTAL's (TWO WHEELER(NT), LIGHT MOTOR VEHICLE, ...), mapped onto
ours by query_filters.classify_live_category, and that mapping is exact for
some categories and not others. Measured (calendar-year totals vs
fuel_category_totals, all states):

| category x powertrain | 2019-2023, 2025      | 2024     | 2026 (in progress) |
|-----------------------|----------------------|----------|--------------------|
| Two-Wheeler x EV      | within 0.02%         | -28.8%   | +6.3%              |
| Two-Wheeler x ICE     | within 2.2%          | +4.3%    | +5.9%              |
| Three-Wheeler x EV/ICE| within 1.6%          | -5.9/+6.7% | +8.9/+7.7%       |
| Four-Wheeler (LMV)    | +10% to +26% every year (LIGHT MOTOR VEHICLE != our Four-Wheeler) |

So the month figure is served ONLY when, for the same scope (state or all
India), category, powertrain and year, the portal table's year total agrees
with fuel_category_totals within MONTH_MATCH_TOLERANCE_PCT. Otherwise the
answer is "no real month figure" with the measured gap as the reason, and
the caller shows the calendar-year total alone. Never an estimate.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.query_filters import classify_live_category, fuel_group
from app.models.models import FuelCategoryTotal, StateMonthCategoryFuelTotal

MONTH_MATCH_TOLERANCE_PCT = 2.0
SOURCE = "state_month_category_fuel_totals"


@dataclass
class MonthAnswer:
    month_count: int | None
    pct_off: float | None
    available: bool
    reason: str | None


async def category_fuel_month(
    db: AsyncSession, *, year: int, month: int, vehicle_category: str, group: str,
    state: str | None = None,
) -> MonthAnswer:
    """`group` is a query_filters.fuel_group bucket (ICE / Hybrid / EV);
    `state` a state_name or None for all India. RTO scope is the caller's
    job (the portal table has no RTO axis -- RTO accounts must be refused
    before calling this)."""
    q = (
        select(StateMonthCategoryFuelTotal.month, StateMonthCategoryFuelTotal.category,
               StateMonthCategoryFuelTotal.fuel, func.sum(StateMonthCategoryFuelTotal.count))
        .where(StateMonthCategoryFuelTotal.year == year)
        .group_by(StateMonthCategoryFuelTotal.month, StateMonthCategoryFuelTotal.category,
                  StateMonthCategoryFuelTotal.fuel)
    )
    if state:
        q = q.where(StateMonthCategoryFuelTotal.state_name == state)
    portal_year = 0
    portal_month = 0
    months_seen: set[int] = set()
    for m, cat, raw_fuel, cnt in (await db.execute(q)).all():
        months_seen.add(int(m))
        if classify_live_category(cat) != vehicle_category or fuel_group(raw_fuel) != group:
            continue
        portal_year += int(cnt or 0)
        if int(m) == month:
            portal_month += int(cnt or 0)

    fq = (
        select(FuelCategoryTotal.fuel_type, func.sum(FuelCategoryTotal.count))
        .where(FuelCategoryTotal.year == year, FuelCategoryTotal.vehicle_category == vehicle_category)
        .group_by(FuelCategoryTotal.fuel_type)
    )
    if state:
        fq = fq.where(FuelCategoryTotal.state_name == state)
    crosstab_year = sum(int(c or 0) for f, c in (await db.execute(fq)).all() if fuel_group(f) == group)

    pct = round((portal_year - crosstab_year) * 100.0 / crosstab_year, 2) if crosstab_year else None
    if month not in months_seen:
        return MonthAnswer(None, pct, False,
                           f"No month-level category x fuel data is stored for {month:02d}/{year}.")
    if crosstab_year == 0 and portal_year == 0:
        return MonthAnswer(0, None, True, None)
    if pct is None or abs(pct) > MONTH_MATCH_TOLERANCE_PCT:
        gap = "has no matching year total" if pct is None else f"differs from the year total by {pct:+.1f}%"
        return MonthAnswer(None, pct, False,
                           f"The monthly source {gap} for {vehicle_category} x {group} in CY {year}, "
                           f"so its month figure is not trustworthy here.")
    return MonthAnswer(portal_month, pct, True, None)
