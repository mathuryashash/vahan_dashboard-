from datetime import datetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.core.query_filters import apply_total_filters, latest_month_with_data
from app.core.auth import get_current_user
from app.core.scope import get_effective_category, get_effective_state, scoped_rto
from app.models.models import Registration, User
from app.core.validation import MAX_YEAR, MIN_YEAR
from app.services.data_freshness import get_freshness

router = APIRouter()

_DEFAULT_YEAR = datetime.now().year


@router.get("/monthly")
async def get_yoy_monthly(
    year_a: int = Query(default=_DEFAULT_YEAR - 1, ge=MIN_YEAR, le=MAX_YEAR),
    year_b: int = Query(default=_DEFAULT_YEAR, ge=MIN_YEAR, le=MAX_YEAR),
    start_month: int = Query(default=1, ge=1, le=12),
    end_month: int = Query(default=12, ge=1, le=12),
    state: str | None = Depends(get_effective_state),
    user_category: str | None = Depends(get_effective_category),
    user_rto: str | None = Depends(scoped_rto),
    db: AsyncSession = Depends(get_db),
):
    # start_month/end_month default to the full year (unchanged behavior) --
    # passing e.g. 4/7 restricts both years to Apr-Jul, the same "same
    # timeline, different years" custom-range comparison as /summary below.
    #
    # apply_total_filters rather than the bare exclude_supplementary this
    # used before: with no category it IS exclude_supplementary (identical
    # query), and with one it swaps to the vehicle_class-dimension rows that
    # actually carry a category instead of stripping them out. Without this
    # clamp a four-wheeler account's YoY chart is the whole market's.
    query_a = apply_total_filters(
        select(Registration.month, func.sum(Registration.count).label("count"))
        .where(Registration.year == year_a, Registration.month >= start_month, Registration.month <= end_month),
        rto_code=user_rto, vehicle_category=user_category,
    ).group_by(Registration.month)

    query_b = apply_total_filters(
        select(Registration.month, func.sum(Registration.count).label("count"))
        .where(Registration.year == year_b, Registration.month >= start_month, Registration.month <= end_month),
        rto_code=user_rto, vehicle_category=user_category,
    ).group_by(Registration.month)

    if state:
        query_a = query_a.where(Registration.state_name == state)
        query_b = query_b.where(Registration.state_name == state)

    result_a = await db.execute(query_a.order_by(Registration.month))
    result_b = await db.execute(query_b.order_by(Registration.month))

    rows_a = {r[0]: r[1] for r in result_a.all()}
    rows_b = {r[0]: r[1] for r in result_b.all()}

    # The stored-but-incomplete newest month (from the data, not today's
    # date). Its growth is withheld: a month scraped part-way through always
    # reads as a fake decline against a full prior-year month.
    freshness = await get_freshness(db)
    partial_b = freshness.partial_month(year_b)
    partial_a = freshness.partial_month(year_a)

    months = sorted(set(rows_a.keys()) | set(rows_b.keys()))
    data = []
    for m in months:
        a = rows_a.get(m, 0)
        # A month absent from rows_b hasn't happened yet / isn't scraped for
        # year_b, not "zero registrations" -- computing (0 - a) / a would
        # report a fake ~-100% decline for months that simply haven't
        # occurred, rather than omitting them like the frontend expects.
        b_row = rows_b.get(m)
        b = b_row or 0
        is_partial = m in (partial_a, partial_b)
        growth = round(((b - a) / a * 100), 2) if (a > 0 and b_row is not None and not is_partial) else None
        data.append(
            {
                "month": m,
                f"year_{year_a}": a,
                f"year_{year_b}": b,
                "growth_percent": growth,
                "is_partial": is_partial,
            }
        )

    return {
        "year_a": year_a, "year_b": year_b, "state": state, "data": data,
        "partial_month": partial_b or partial_a,
        "partial_month_year": (year_b if partial_b else year_a) if (partial_b or partial_a) else None,
        # When the partial month was scraped (lets the UI say "data through
        # 19 Sep" instead of guessing progress from today's date).
        "data_scraped_at": freshness.last_scrape_at.isoformat() if freshness.last_scrape_at else None,
    }


@router.get("/summary")
async def get_yoy_summary(
    year_a: int = Query(default=_DEFAULT_YEAR - 1, ge=MIN_YEAR, le=MAX_YEAR),
    year_b: int = Query(default=_DEFAULT_YEAR, ge=MIN_YEAR, le=MAX_YEAR),
    start_month: int = Query(default=1, ge=1, le=12),
    end_month: int = Query(default=12, ge=1, le=12),
    state: str | None = Depends(get_effective_state),
    user_category: str | None = Depends(get_effective_category),
    user_rto: str | None = Depends(scoped_rto),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    # Returns no state breakdown, but it does return a TOTAL, and a scoped
    # account's total must be its own: this was the one YoY endpoint with no
    # geo-clamp at all (/monthly right above already clamps state), so a
    # state- or RTO-tier account read an all-India figure here. Clamped on
    # both axes now, same dependencies as /monthly.
    # start_month/end_month default to the full year, giving the same
    # Jan-through-latest-month total as before. A custom range (e.g. 4/7 for
    # Apr-Jul) compares that exact window across both years instead --
    # "same timeline, different years", generalizing the YTD-only comparison
    # this endpoint used to be limited to.
    # Cut each year at its last COMPLETE scraped month, derived from the
    # data: the newest month of the newest scraped year is excluded when it
    # was still in progress at scrape time (data froze 2026-09-19, so Sep 2026
    # is partial even in October). Older years are complete through their
    # newest month. Today's date plays no part.
    freshness = await get_freshness(db)
    max_month_a = freshness.complete_through(year_a, await latest_month_with_data(db, year_a))
    max_month_b = freshness.complete_through(year_b, await latest_month_with_data(db, year_b))
    candidates = [m for m in (max_month_a, max_month_b) if m is not None]
    # Cap at whichever year has less data so far within the requested range:
    # comparing a full Apr-Jul against a partial Apr-Jun (year still in
    # progress) produces a nonsensical, deeply negative "growth" number.
    # Same fix already applied to summary.get_dashboard_kpis.
    effective_end = min([end_month, *candidates]) if candidates else end_month
    partial = freshness.partial_month(year_b) or freshness.partial_month(year_a)
    meta = {
        "compare_through_month": effective_end,
        "start_month": start_month,
        "partial_month": partial,
        "partial_month_year": (year_b if freshness.partial_month(year_b) else year_a) if partial else None,
        "last_complete_month": (
            f"{freshness.last_complete_month()[0]}-{freshness.last_complete_month()[1]:02d}"
            if freshness.last_complete_month() else None
        ),
    }
    if effective_end < start_month:
        # N4: the requested window starts after the last complete month, so
        # there is nothing comparable. Say so instead of "0 vs 0, +0.0%",
        # which a customer reads as "no registrations".
        return {
            f"total_{year_a}": None, f"total_{year_b}": None, "growth_percent": None, **meta,
            "empty_reason": "window after last complete month",
        }

    q_a = apply_total_filters(select(func.sum(Registration.count)).where(
        Registration.year == year_a, Registration.month >= start_month, Registration.month <= effective_end
    ), state=state, rto_code=user_rto, vehicle_category=user_category)
    q_b = apply_total_filters(select(func.sum(Registration.count)).where(
        Registration.year == year_b, Registration.month >= start_month, Registration.month <= effective_end
    ), state=state, rto_code=user_rto, vehicle_category=user_category)

    result_a = await db.execute(q_a)
    result_b = await db.execute(q_b)

    total_a = result_a.scalar() or 0
    total_b = result_b.scalar() or 0
    growth = round(((total_b - total_a) / total_a * 100), 2) if total_a > 0 else None

    return {
        f"total_{year_a}": total_a,
        f"total_{year_b}": total_b,
        "growth_percent": growth,
        # partial_month: the stored-but-incomplete month (excluded above), so
        # the YoY page's partial-month notice comes from the data, not the date.
        **meta,
        "empty_reason": None,
    }
