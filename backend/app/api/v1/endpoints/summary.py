from datetime import datetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from app.core.database import get_db
from app.core.query_filters import apply_fuel_group_filter, apply_total_filters, exclude_supplementary, latest_month_with_data
from app.models.models import Registration
from app.schemas.schemas import DashboardKPIs
from app.core.config import settings

router = APIRouter()

# Evaluated once at import time rather than hardcoded, so these endpoints
# don't need a source change every January.
_DEFAULT_YEAR = datetime.now().year


@router.get("/available-years")
async def get_available_years(db: AsyncSession = Depends(get_db)):
    """Years that actually have real (non-supplementary) scraped data, newest
    first. The Overview year filter used to hardcode [2024, 2025, 2026]; as
    more years get backfilled (see scraper/backfill_all_years.py) that list
    would silently go stale and hide newly-added years unless a source change
    shipped alongside every scrape. Driving the filter from this instead
    means a new year becomes selectable the moment it's scraped, with no
    frontend deploy needed."""
    result = await db.execute(
        exclude_supplementary(select(Registration.year).distinct()).order_by(Registration.year.desc())
    )
    return [row[0] for row in result.all()]


@router.get("/kpis", response_model=DashboardKPIs)
async def get_dashboard_kpis(
    year: int | None = None,
    month: int | None = None,
    state: str | None = None,
    vehicle_class: str | None = None,
    vehicle_category: str | None = None,
    commercial_tier: str | None = None,
    fuel_group: str | None = None,
    maker: str | None = None,
    vehicle_model: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    current_year = year or _DEFAULT_YEAR
    prev_year = current_year - 1

    # When no specific month is requested, compare year-to-date rather than
    # full calendar year vs full calendar year: if current_year only has data
    # through June (e.g. it's the in-progress year), comparing 6 months of
    # current_year against 12 months of prev_year produces a nonsensical,
    # deeply negative "growth" number. Cap both periods at the latest month
    # that actually has data for current_year -- computed as a scalar
    # subquery (evaluated server-side) rather than a separate awaited round
    # trip, since this endpoint's latency is dominated by round-trip count,
    # not query cost (each of these is a fast indexed lookup on its own).
    max_month_subq = (
        select(func.max(Registration.month)).where(Registration.year == current_year).scalar_subquery()
    )
    month_filter = (Registration.month == month) if month else (Registration.month <= max_month_subq)

    # Current + previous period totals in one grouped query instead of two --
    # both use the same cutoff month, so there's nothing year-specific about
    # the filter that needs two separate round trips.
    q_totals = select(Registration.year, func.sum(Registration.count).label("total")).where(
        Registration.year.in_([current_year, prev_year]), month_filter
    )
    q_totals = apply_fuel_group_filter(
        apply_total_filters(
            q_totals, state=state, vehicle_class=vehicle_class, vehicle_category=vehicle_category,
            commercial_tier=commercial_tier, maker=maker, vehicle_model=vehicle_model,
        ),
        fuel_group,
    ).group_by(Registration.year)

    result_totals = await db.execute(q_totals)
    totals_by_year = dict(result_totals.all())
    total_this_period = totals_by_year.get(current_year) or 0
    total_prev_period = totals_by_year.get(prev_year) or 0

    # Calculate YoY Growth
    yoy_growth = 0.0
    if total_prev_period > 0:
        yoy_growth = round(
            ((total_this_period - total_prev_period) / total_prev_period) * 100, 2
        )

    # Top State Query
    q_top_state = (
        select(Registration.state_name, func.sum(Registration.count).label("total"))
        .where(Registration.year == current_year, month_filter)
    )
    q_top_state = apply_fuel_group_filter(
        apply_total_filters(
            q_top_state, state=state, vehicle_class=vehicle_class, vehicle_category=vehicle_category,
            commercial_tier=commercial_tier, maker=maker, vehicle_model=vehicle_model,
        ),
        fuel_group,
    )

    q_top_state = q_top_state.group_by(Registration.state_name).order_by(desc("total")).limit(1)
    result_top = await db.execute(q_top_state)
    top_row = result_top.first()
    top_state = top_row[0] if top_row else "N/A"
    top_state_count = top_row[1] if top_row else 0

    # VAHAN4 supplies month-wise, not day-wise, registrations. Avoid a large
    # scan for a date that cannot exist and expose an honest daily average
    # instead. The API field name stays stable for the current frontend.
    period_months = month or await latest_month_with_data(db, current_year) or 1
    total_today = int(total_this_period / (period_months * 30)) if total_this_period > 0 else 0

    last_updated = settings.LAST_UPDATED

    return DashboardKPIs(
        total_registrations_today=total_today,
        total_this_month=total_this_period,
        yoy_growth_percent=yoy_growth,
        top_state=top_state,
        top_state_count=top_state_count,
        last_updated=last_updated,
    )


@router.get("/trend")
async def get_trend(
    year: int = _DEFAULT_YEAR,
    state: str | None = None,
    vehicle_class: str | None = None,
    vehicle_category: str | None = None,
    commercial_tier: str | None = None,
    fuel_group: str | None = None,
    maker: str | None = None,
    vehicle_model: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Month-wise registration trend for the year. There is no day-level
    breakdown to fall back to when a specific month is selected elsewhere on
    the page (see get_month_detail's docstring) -- the trend chart always
    shows the full year's month-by-month shape."""
    query = select(
        Registration.month, func.sum(Registration.count).label("count")
    ).where(Registration.year == year)
    query = apply_fuel_group_filter(
        apply_total_filters(
            query, state=state, vehicle_class=vehicle_class, vehicle_category=vehicle_category,
            commercial_tier=commercial_tier, maker=maker, vehicle_model=vehicle_model,
        ),
        fuel_group,
    )

    query = query.group_by(Registration.month).order_by(Registration.month)
    result = await db.execute(query)
    rows = result.all()
    return [{"month": r[0], "count": r[1]} for r in rows]


@router.get("/state-ranking")
async def get_state_ranking(
    year: int = _DEFAULT_YEAR,
    month: int | None = None,
    state: str | None = None,
    vehicle_class: str | None = None,
    vehicle_category: str | None = None,
    commercial_tier: str | None = None,
    fuel_group: str | None = None,
    maker: str | None = None,
    vehicle_model: str | None = None,
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
):
    query = select(
        Registration.state_name, func.sum(Registration.count).label("total")
    ).where(Registration.year == year)

    if month:
        query = query.where(Registration.month == month)
    query = apply_fuel_group_filter(
        apply_total_filters(
            query, state=state, vehicle_class=vehicle_class, vehicle_category=vehicle_category,
            commercial_tier=commercial_tier, maker=maker, vehicle_model=vehicle_model,
        ),
        fuel_group,
    )

    query = query.group_by(Registration.state_name).order_by(desc("total")).limit(limit)
    result = await db.execute(query)
    rows = result.all()

    total_all = sum(r[1] for r in rows)
    return [
        {
            "state_name": r[0],
            "total_count": r[1],
            "share_percent": round((r[1] / total_all * 100) if total_all > 0 else 0, 2),
        }
        for r in rows
    ]


async def _period_sum(
    db: AsyncSession,
    year: int,
    *,
    month: int | None = None,
    month_lt: int | None = None,
    state: str | None = None,
    vehicle_class: str | None = None,
    vehicle_category: str | None = None,
    commercial_tier: str | None = None,
    fuel_group: str | None = None,
    maker: str | None = None,
    vehicle_model: str | None = None,
) -> int:
    query = select(func.sum(Registration.count)).where(Registration.year == year)
    if month is not None:
        query = query.where(Registration.month == month)
    if month_lt is not None:
        query = query.where(Registration.month < month_lt)
    query = apply_fuel_group_filter(
        apply_total_filters(
            query, state=state, vehicle_class=vehicle_class, vehicle_category=vehicle_category,
            commercial_tier=commercial_tier, maker=maker, vehicle_model=vehicle_model,
        ),
        fuel_group,
    )
    result = await db.execute(query)
    return result.scalar() or 0


def _growth_percent(current: float, previous: float | None) -> float | None:
    if previous is None or previous <= 0:
        return None
    return round((current - previous) / previous * 100, 2)


@router.get("/month-detail")
async def get_month_detail(
    year: int,
    month: int,
    state: str | None = None,
    vehicle_class: str | None = None,
    vehicle_category: str | None = None,
    commercial_tier: str | None = None,
    fuel_group: str | None = None,
    maker: str | None = None,
    vehicle_model: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Registrations for a specific month, plus year-to-date through that
    month, each compared against the same point last year.

    The live VAHAN4 site has no day-level granularity at all -- its finest
    X-axis option is "Month Wise" (confirmed against the live site's own
    axis-selector options; there is no "Day Wise"). An earlier version of
    this endpoint was built around a day picker and a day/month-to-date
    breakdown, using a `Registration.day` column that real scraped data can
    never populate -- it 404'd unconditionally once synthetic data was
    replaced. This version only reports what the source can actually supply:
    a whole month's total and year-to-date, both real, no estimation needed.
    """
    prev_year = year - 1
    filters = dict(
        state=state, vehicle_class=vehicle_class, vehicle_category=vehicle_category,
        commercial_tier=commercial_tier, fuel_group=fuel_group, maker=maker, vehicle_model=vehicle_model,
    )

    month_count = await _period_sum(db, year, month=month, **filters)
    prior_months_count = await _period_sum(db, year, month_lt=month, **filters)
    ytd_count = prior_months_count + month_count

    month_prev = await _period_sum(db, prev_year, month=month, **filters)
    prior_months_prev = await _period_sum(db, prev_year, month_lt=month, **filters)
    ytd_prev = prior_months_prev + month_prev

    return {
        "year": year,
        "month": month,
        "month_count": month_count,
        "month_yoy_growth_percent": _growth_percent(month_count, month_prev),
        "ytd_count": ytd_count,
        "ytd_yoy_growth_percent": _growth_percent(ytd_count, ytd_prev),
    }
