from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import Select
from app.models.models import Registration


def apply_common_filters(
    query: Select,
    *,
    state: str | None = None,
    vehicle_class: str | None = None,
    maker: str | None = None,
    vehicle_model: str | None = None,
) -> Select:
    """Apply the state/vehicle_class/maker/vehicle_model filters shared by
    most registration-aggregation endpoints. Month is deliberately excluded:
    callers need different month semantics (exact match vs. "up to" a cutoff
    month for year-to-date comparisons), so they apply it themselves.
    """
    if state:
        query = query.where(Registration.state_name == state)
    if vehicle_class:
        query = query.where(Registration.vehicle_class == vehicle_class)
    if maker:
        query = query.where(Registration.maker == maker)
    if vehicle_model:
        query = query.where(Registration.vehicle_model == vehicle_model)
    return query


def exclude_supplementary(query: Select) -> Select:
    """For queries that sum `count` toward an overall total (KPIs, trends,
    state rankings, month-detail): the live scraper can only pivot on one
    dimension per RTO visit, so a single RTO/month's registrations may be
    represented by multiple rows -- a full maker breakdown, a full vehicle-class
    breakdown, a full fuel-type breakdown -- each independently summing to the
    true total. Summing across all of them would double- or triple-count.
    is_supplementary=True marks the non-canonical passes (vehicle_class/fuel);
    total-sum queries should exclude them. Breakdown-by-category queries
    (categories.py) do the opposite -- they WANT the supplementary rows -- so
    this is deliberately a separate opt-in helper, not baked into
    apply_common_filters which both kinds of query share.
    """
    return query.where(Registration.is_supplementary.isnot(True))


def apply_total_filters(
    query: Select,
    *,
    state: str | None = None,
    vehicle_class: str | None = None,
    maker: str | None = None,
    vehicle_model: str | None = None,
) -> Select:
    """apply_common_filters, for queries that sum toward an overall total
    (KPIs, trend, state-ranking) -- also excludes supplementary rows, unless
    vehicle_class narrows to one specific real class. The canonical maker-pass
    (is_supplementary=False) always stores vehicle_class='All', so it can
    never match a specific class filter anyway; the only rows that ever carry
    a real class are the vehicle_class-dimension pass (is_supplementary=True)
    and synthetic seed data. Excluding supplementary rows in that case would
    silently zero out every category-filtered total for live-scraped years,
    since it would strip out the only rows that could ever match.
    """
    if not vehicle_class or vehicle_class == "All":
        query = exclude_supplementary(query)
    return apply_common_filters(
        query, state=state, vehicle_class=vehicle_class, maker=maker, vehicle_model=vehicle_model
    )


async def latest_month_with_data(db: AsyncSession, year: int) -> int | None:
    """Highest month with any registration row for `year`, or None if the
    year has no data yet. Used to cap a year-to-date comparison at the same
    point in both years instead of comparing a full year against a partial
    one."""
    result = await db.execute(select(func.max(Registration.month)).where(Registration.year == year))
    return result.scalar()
