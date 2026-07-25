from datetime import datetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.core.query_filters import exclude_supplementary, latest_month_with_data
from app.models.models import Registration

router = APIRouter()

_DEFAULT_YEAR = datetime.now().year


@router.get("/monthly")
async def get_yoy_monthly(
    year_a: int = Query(default=_DEFAULT_YEAR - 1),
    year_b: int = Query(default=_DEFAULT_YEAR),
    state: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    query_a = exclude_supplementary(
        select(Registration.month, func.sum(Registration.count).label("count"))
        .where(Registration.year == year_a)
    ).group_by(Registration.month)

    query_b = exclude_supplementary(
        select(Registration.month, func.sum(Registration.count).label("count"))
        .where(Registration.year == year_b)
    ).group_by(Registration.month)

    if state:
        query_a = query_a.where(Registration.state_name == state)
        query_b = query_b.where(Registration.state_name == state)

    result_a = await db.execute(query_a.order_by(Registration.month))
    result_b = await db.execute(query_b.order_by(Registration.month))

    rows_a = {r[0]: r[1] for r in result_a.all()}
    rows_b = {r[0]: r[1] for r in result_b.all()}

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
        growth = round(((b - a) / a * 100), 2) if (a > 0 and b_row is not None) else None
        data.append(
            {
                "month": m,
                f"year_{year_a}": a,
                f"year_{year_b}": b,
                "growth_percent": growth,
            }
        )

    return {"year_a": year_a, "year_b": year_b, "state": state, "data": data}


@router.get("/summary")
async def get_yoy_summary(
    year_a: int = Query(default=_DEFAULT_YEAR - 1),
    year_b: int = Query(default=_DEFAULT_YEAR),
    db: AsyncSession = Depends(get_db),
):
    # Cap both years at whichever has less data so far: comparing a full
    # calendar year against an in-progress one (e.g. 12 months of 2025 vs
    # 7 months of 2026) produces a nonsensical, deeply negative "growth"
    # number. Same fix already applied to summary.get_dashboard_kpis.
    max_month_a = await latest_month_with_data(db, year_a)
    max_month_b = await latest_month_with_data(db, year_b)
    candidates = [m for m in (max_month_a, max_month_b) if m is not None]
    compare_month = min(candidates) if candidates else None

    q_a = exclude_supplementary(select(func.sum(Registration.count)).where(Registration.year == year_a))
    q_b = exclude_supplementary(select(func.sum(Registration.count)).where(Registration.year == year_b))
    if compare_month is not None:
        q_a = q_a.where(Registration.month <= compare_month)
        q_b = q_b.where(Registration.month <= compare_month)

    result_a = await db.execute(q_a)
    result_b = await db.execute(q_b)

    total_a = result_a.scalar() or 0
    total_b = result_b.scalar() or 0
    growth = round(((total_b - total_a) / total_a * 100), 2) if total_a > 0 else 0.0

    return {
        f"total_{year_a}": total_a,
        f"total_{year_b}": total_b,
        "compare_through_month": compare_month,
        "growth_percent": growth,
    }
