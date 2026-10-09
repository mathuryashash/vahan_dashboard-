import calendar
import time
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, text
from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.query_filters import apply_fuel_group_filter, apply_total_filters, latest_month_with_data
from app.core.scope import get_effective_category, get_effective_state, scoped_rto
from app.core.cache import TTLCache, single_flight
from app.models.models import Registration, User
from app.schemas.schemas import DashboardKPIs, MonthCount, MonthDetail, StateRankingItem
from app.core.config import settings
from app.services.data_freshness import get_freshness
from app.core.validation import MAX_MONTH, MAX_YEAR, MIN_MONTH, MIN_YEAR

router = APIRouter()

# Evaluated once at import time rather than hardcoded, so these endpoints
# don't need a source change every January.
_DEFAULT_YEAR = datetime.now().year

# DISTINCT year over 26M+ rows forces Postgres into a full parallel seq scan
# (confirmed via EXPLAIN ANALYZE: ~17.5s, 938k buffer reads) since it has no
# way to skip-scan for a handful of distinct values. The result changes at
# most a few times a day (a new year appearing, or a backfill run) -- caching
# it for a few minutes turns every request but the first per window from a
# 17s+ full scan into a dict lookup, which is a far better trade than adding
# an index Postgres won't use for this query shape anyway.
_available_years_cache: dict = {"years": None, "at": 0.0}
_AVAILABLE_YEARS_CACHE_TTL_SECONDS = 300
_AVAILABLE_YEARS_SQL = text("""
    WITH RECURSIVE y AS (
        (SELECT year FROM registrations WHERE is_supplementary IS NOT TRUE ORDER BY year DESC LIMIT 1)
        UNION ALL
        SELECT (SELECT r.year FROM registrations r
                WHERE r.is_supplementary IS NOT TRUE AND r.year < y.year
                ORDER BY r.year DESC LIMIT 1)
        FROM y WHERE y.year IS NOT NULL
    )
    SELECT year FROM y WHERE year IS NOT NULL ORDER BY year DESC
""")


@router.get("/available-years", response_model=list[int])
@single_flight
async def get_available_years(
    db: AsyncSession = Depends(get_db),
    # Every sibling route in this file requires a user; this one was missing
    # it and answered 200 to an unauthenticated caller (found in a security
    # review). The payload is only a list of years, but nothing here is meant
    # to be public.
    _user: User = Depends(get_current_user),
):
    """Years that actually have real (non-supplementary) scraped data, newest
    first. The Overview year filter used to hardcode [2024, 2025, 2026]; as
    more years get backfilled (see scraper/backfill_all_years.py) that list
    would silently go stale and hide newly-added years unless a source change
    shipped alongside every scrape. Driving the filter from this instead
    means a new year becomes selectable the moment it's scraped, with no
    frontend deploy needed."""
    now = time.monotonic()
    if _available_years_cache["years"] is not None and now - _available_years_cache["at"] < _AVAILABLE_YEARS_CACHE_TTL_SECONDS:
        return _available_years_cache["years"]

    # Recursive "loose index scan": one index probe per distinct year on the
    # partial index idx_reg_year_supp_state_count (WHERE is_supplementary IS
    # NOT TRUE) instead of DISTINCT over ~10M rows. 20ms vs 245ms on prod,
    # identical year list (verified with SELECT on the prod DB).
    result = await db.execute(_AVAILABLE_YEARS_SQL)
    years = [row[0] for row in result.all()]
    _available_years_cache["years"] = years
    _available_years_cache["at"] = now
    return years


# kpis/trend/state-ranking are fired unconditionally on every Overview page
# load (Overview.tsx has no "don't refetch" gate), and each is a SUM over a
# 26M+ row table -- 1.6-2.3s apiece even with fresh table statistics (see
# the VACUUM ANALYZE incidents in git history), noticeably more before this
# session's autovacuum tuning. The vast majority of page loads share the
# exact same default filters (no state/category/maker picked yet), so a
# short TTL turns nearly every request after the first per window into a
# dict lookup. Keyed on the resolved filter params only, never the DB
# session -- state is already scope-clamped by the time it reaches here
# (see get_effective_state), so a state/RTO-scoped user's cache entries
# naturally stay separate from a national user's.
_KPIS_CACHE_TTL_SECONDS = 90
_kpis_cache = TTLCache(_KPIS_CACHE_TTL_SECONDS)


@router.get("/kpis", response_model=DashboardKPIs)
@single_flight
async def get_dashboard_kpis(
    year: int | None = Query(None, ge=MIN_YEAR, le=MAX_YEAR),
    month: int | None = Query(None, ge=MIN_MONTH, le=MAX_MONTH),
    state: str | None = Depends(get_effective_state),
    user_rto: str | None = Depends(scoped_rto),
    vehicle_class: str | None = None,
    vehicle_category: str | None = Depends(get_effective_category),
    commercial_tier: str | None = None,
    fuel_group: str | None = None,
    maker: str | None = None,
    vehicle_model: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    cache_key = (year, month, state, user_rto, vehicle_class, vehicle_category, commercial_tier, fuel_group, maker, vehicle_model)
    cached = _kpis_cache.get(cache_key)
    if cached is not None:
        return cached

    current_year = year or _DEFAULT_YEAR
    prev_year = current_year - 1

    # Newest month with any data for current_year (one indexed lookup, ~3ms).
    # The headline total covers Jan..max_month, as before.
    max_month = await latest_month_with_data(db, current_year)
    # YoY must compare like with like. Cutting at max_month compared a
    # PARTIAL month against a full one: the data froze mid-September, so
    # "Jan-Sep 2026 vs Jan-Sep 2025" was really Jan-19 Sep vs Jan-30 Sep --
    # a fake decline. Cut at the last COMPLETE scraped month instead, derived
    # from the data (when the newest month was scraped), not today's date.
    freshness = await get_freshness(db)
    partial = freshness.partial_month(current_year)
    incomplete = bool(month) and freshness.month_incomplete(current_year, month)
    if month:
        # An explicitly requested month that is the partial month, or any
        # month after the newest scraped one, is not comparable either
        # (kpis?year=2026&month=9 read -21.95%; month=11 read -100%).
        compare_through = None if incomplete else month
    else:
        compare_through = freshness.complete_through(current_year, max_month)
    cutoff = month if month else max_month

    cur, prev = Registration.year == current_year, Registration.year == prev_year
    if month:
        month_filter = Registration.month == month
        this_expr = func.sum(Registration.count).filter(cur)
        cur_cmp_expr = this_expr
        prev_cmp_expr = func.sum(Registration.count).filter(prev)
    else:
        # A literal bound (not the old max(month) scalar subquery) so the
        # planner can use idx_reg_year_month_supp_count directly. Rows above
        # max_month cannot exist for current_year, and prev_year only needs
        # months <= compare_through <= max_month, so the sums are unchanged.
        month_filter = Registration.month <= (cutoff or 0)
        this_expr = func.sum(Registration.count).filter(cur)
        cur_cmp_expr = func.sum(Registration.count).filter(cur, Registration.month <= (compare_through or 0))
        prev_cmp_expr = func.sum(Registration.count).filter(prev, Registration.month <= (compare_through or 0))

    # Headline total + both comparison totals in one round trip.
    q_totals = select(this_expr, cur_cmp_expr, prev_cmp_expr).where(
        Registration.year.in_([current_year, prev_year]), month_filter
    )
    q_totals = apply_fuel_group_filter(
        apply_total_filters(
            q_totals, state=state, rto_code=user_rto, vehicle_class=vehicle_class, vehicle_category=vehicle_category,
            commercial_tier=commercial_tier, fuel_group=fuel_group, maker=maker, vehicle_model=vehicle_model,
        ),
        fuel_group,
    )

    total_this_period, cur_compare, prev_compare = (await db.execute(q_totals)).one()
    total_this_period = total_this_period or 0
    cur_compare = cur_compare or 0
    prev_compare = prev_compare or 0

    # YoY Growth: None (not 0.0) when there is no complete month to compare
    # or no prior-year data -- "unknown" must not render as "flat".
    yoy_growth = None
    if prev_compare > 0 and compare_through:
        yoy_growth = round(((cur_compare - prev_compare) / prev_compare) * 100, 2)

    # Top State Query. No month predicate unless a month was asked for: the
    # old `month <= max(month) of current_year` was a tautology on
    # current_year rows that cost a 1.5s BitmapAnd (identical top state and
    # count verified on prod: Uttar Pradesh 3,006,936 for 2026).
    q_top_state = select(Registration.state_name, func.sum(Registration.count).label("total")).where(
        Registration.year == current_year
    )
    if month:
        q_top_state = q_top_state.where(Registration.month == month)
    q_top_state = apply_fuel_group_filter(
        apply_total_filters(
            q_top_state, state=state, rto_code=user_rto, vehicle_class=vehicle_class, vehicle_category=vehicle_category,
            commercial_tier=commercial_tier, fuel_group=fuel_group, maker=maker, vehicle_model=vehicle_model,
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
    # `month or ...` divided a SINGLE month's total by that month's index:
    # picking September narrowed the numerator to one month while the
    # denominator became 9 * 30 = 270 days, reading 4,383/day against a true
    # ~39,447. The card then appeared to fall away steadily through the year,
    # entirely as an artifact of the month number. One month selected means
    # one month of days.
    # The partial month only holds data up to the scrape day: dividing its
    # 9 days of Oct by 30 read 15,618/day against a true ~52k.
    total_today = int(total_this_period / _period_days(current_year, month, max_month, partial, freshness.last_scrape_at)) if total_this_period > 0 else 0

    last_updated = settings.LAST_UPDATED or freshness.last_updated_str

    kpis = DashboardKPIs(
        total_registrations_today=total_today,
        total_this_month=total_this_period,
        yoy_growth_percent=yoy_growth,
        top_state=top_state,
        top_state_count=top_state_count,
        last_updated=last_updated,
        yoy_compare_through_month=compare_through,
        partial_month=partial,
        latest_month=max_month,
        month_incomplete=incomplete,
    )
    _kpis_cache.set(cache_key, kpis)
    return kpis


def _period_days(year: int, month: int | None, max_month: int | None, partial: int | None, scraped_at) -> int:
    """Calendar days the period's data covers; the partial month counts only
    up to the (IST) day it was scraped."""
    months = [month] if month else range(1, (max_month or 1) + 1)
    days = 0
    for m in months:
        if m == partial and scraped_at is not None:
            days += scraped_at.astimezone(timezone(timedelta(hours=5, minutes=30))).day
        else:
            days += calendar.monthrange(year, m)[1]
    return max(days, 1)


_TREND_CACHE_TTL_SECONDS = 90
_trend_cache = TTLCache(_TREND_CACHE_TTL_SECONDS)


@router.get("/trend", response_model=list[MonthCount])
@single_flight
async def get_trend(
    year: int = Query(_DEFAULT_YEAR, ge=MIN_YEAR, le=MAX_YEAR),
    state: str | None = Depends(get_effective_state),
    user_rto: str | None = Depends(scoped_rto),
    vehicle_class: str | None = None,
    vehicle_category: str | None = Depends(get_effective_category),
    commercial_tier: str | None = None,
    fuel_group: str | None = None,
    maker: str | None = None,
    vehicle_model: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    cache_key = (year, state, user_rto, vehicle_class, vehicle_category, commercial_tier, fuel_group, maker, vehicle_model)
    cached = _trend_cache.get(cache_key)
    if cached is not None:
        return cached
    """Month-wise registration trend for the year. There is no day-level
    breakdown to fall back to when a specific month is selected elsewhere on
    the page (see get_month_detail's docstring) -- the trend chart always
    shows the full year's month-by-month shape."""
    query = select(
        Registration.month, func.sum(Registration.count).label("count")
    ).where(Registration.year == year)
    query = apply_fuel_group_filter(
        apply_total_filters(
            query, state=state, rto_code=user_rto, vehicle_class=vehicle_class, vehicle_category=vehicle_category,
            commercial_tier=commercial_tier, fuel_group=fuel_group, maker=maker, vehicle_model=vehicle_model,
        ),
        fuel_group,
    )

    query = query.group_by(Registration.month).order_by(Registration.month)
    result = await db.execute(query)
    rows = result.all()
    trend = [{"month": r[0], "count": r[1]} for r in rows]
    _trend_cache.set(cache_key, trend)
    return trend


_STATE_RANKING_CACHE_TTL_SECONDS = 90
_state_ranking_cache = TTLCache(_STATE_RANKING_CACHE_TTL_SECONDS)


@router.get("/state-ranking", response_model=list[StateRankingItem])
@single_flight
async def get_state_ranking(
    year: int = Query(_DEFAULT_YEAR, ge=MIN_YEAR, le=MAX_YEAR),
    month: int | None = Query(None, ge=MIN_MONTH, le=MAX_MONTH),
    state: str | None = Depends(get_effective_state),
    user_rto: str | None = Depends(scoped_rto),
    vehicle_class: str | None = None,
    vehicle_category: str | None = Depends(get_effective_category),
    commercial_tier: str | None = None,
    fuel_group: str | None = None,
    maker: str | None = None,
    vehicle_model: str | None = None,
    # Bounded: a bare `int` let a negative through to Postgres, which answers
    # "LIMIT must not be negative" as a 500 rather than a clean 422. Upper
    # bound sits above the 100 the frontend's widest caller asks for.
    limit: int = Query(default=10, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    cache_key = (year, month, state, user_rto, vehicle_class, vehicle_category, commercial_tier, fuel_group, maker, vehicle_model, limit)
    cached = _state_ranking_cache.get(cache_key)
    if cached is not None:
        return cached

    query = select(
        Registration.state_name, func.sum(Registration.count).label("total")
    ).where(Registration.year == year)

    if month:
        query = query.where(Registration.month == month)
    query = apply_fuel_group_filter(
        apply_total_filters(
            query, state=state, rto_code=user_rto, vehicle_class=vehicle_class, vehicle_category=vehicle_category,
            commercial_tier=commercial_tier, fuel_group=fuel_group, maker=maker, vehicle_model=vehicle_model,
        ),
        fuel_group,
    )

    # Denominator BEFORE the limit. Summing the returned rows made every
    # share_percent a share of the top-`limit` subtotal, so the ten bars
    # always added to exactly 100% and each state read high -- Uttar Pradesh
    # showed 18.84% against a true national 13.30%, and that inflated figure
    # shipped into client CSV exports. comparison.py's all-states ranking
    # already builds a separate unlimited total for this exact reason; the
    # pattern was never back-ported here, so Overview and Comparison
    # disagreed on the same state's share for the same year.
    total_query = apply_fuel_group_filter(
        apply_total_filters(
            select(func.sum(Registration.count)).where(
                Registration.year == year,
                *([Registration.month == month] if month else []),
            ),
            state=state, rto_code=user_rto, vehicle_class=vehicle_class,
            vehicle_category=vehicle_category, commercial_tier=commercial_tier,
            fuel_group=fuel_group, maker=maker, vehicle_model=vehicle_model,
        ),
        fuel_group,
    )
    total_all = (await db.execute(total_query)).scalar() or 0

    query = query.group_by(Registration.state_name).order_by(desc("total")).limit(limit)
    result = await db.execute(query)
    rows = result.all()
    ranking = [
        {
            "state_name": r[0],
            "total_count": r[1],
            "share_percent": round((r[1] / total_all * 100) if total_all > 0 else 0, 2),
        }
        for r in rows
    ]
    _state_ranking_cache.set(cache_key, ranking)
    return ranking


async def _period_sum(
    db: AsyncSession,
    year: int,
    *,
    month: int | None = None,
    month_lt: int | None = None,
    state: str | None = None,
    rto_code: str | None = None,
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
            query, state=state, rto_code=rto_code, vehicle_class=vehicle_class, vehicle_category=vehicle_category,
            commercial_tier=commercial_tier, fuel_group=fuel_group, maker=maker, vehicle_model=vehicle_model,
        ),
        fuel_group,
    )
    result = await db.execute(query)
    return result.scalar() or 0


def _growth_percent(current: float, previous: float | None) -> float | None:
    if previous is None or previous <= 0:
        return None
    return round((current - previous) / previous * 100, 2)


@router.get("/month-detail", response_model=MonthDetail)
async def get_month_detail(
    year: int = Query(..., ge=MIN_YEAR, le=MAX_YEAR),
    month: int = Query(..., ge=MIN_MONTH, le=MAX_MONTH),
    state: str | None = Depends(get_effective_state),
    user_rto: str | None = Depends(scoped_rto),
    vehicle_class: str | None = None,
    vehicle_category: str | None = Depends(get_effective_category),
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
        state=state, rto_code=user_rto, vehicle_class=vehicle_class, vehicle_category=vehicle_category,
        commercial_tier=commercial_tier, fuel_group=fuel_group, maker=maker, vehicle_model=vehicle_model,
    )

    month_count = await _period_sum(db, year, month=month, **filters)
    prior_months_count = await _period_sum(db, year, month_lt=month, **filters)
    ytd_count = prior_months_count + month_count

    # A partial or not-yet-scraped month vs a full one is a fake decline
    # (month=11 read -100%, the partial October -88.8%): withhold both YoYs.
    incomplete = (await get_freshness(db)).month_incomplete(year, month)
    month_growth = ytd_growth = None
    if not incomplete:
        month_prev = await _period_sum(db, prev_year, month=month, **filters)
        prior_months_prev = await _period_sum(db, prev_year, month_lt=month, **filters)
        month_growth = _growth_percent(month_count, month_prev)
        ytd_growth = _growth_percent(ytd_count, prior_months_prev + month_prev)

    return {
        "year": year,
        "month": month,
        "month_count": month_count,
        "month_yoy_growth_percent": month_growth,
        "ytd_count": ytd_count,
        "ytd_yoy_growth_percent": ytd_growth,
        "month_incomplete": incomplete,
    }
