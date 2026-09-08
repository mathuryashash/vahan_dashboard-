from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, or_, and_
from app.core.database import get_db
from app.core.query_filters import exclude_supplementary
from app.core.scope import require_rto_code, require_state_code
from app.core.cache import TTLCache
from app.models.models import Registration

router = APIRouter()

# Same cost shape and same fix as summary.py/categories.py's hot endpoints --
# both of these scan the 26M-row registrations table (state-wide or one
# RTO's full FY), and RTO Analysis re-fires them on every state/year/RTO
# pick.
_CACHE_TTL_SECONDS = 90
_rto_list_cache = TTLCache(_CACHE_TTL_SECONDS)
_rto_analysis_cache = TTLCache(_CACHE_TTL_SECONDS)


def fy_filter(fy_year: int):
    """Indian financial year: April `fy_year` through March `fy_year + 1`.
    Month values never collide across the two calendar years (Apr-Dec vs
    Jan-Mar), so downstream DISTINCT month/aggregate math stays correct.
    """
    return or_(
        and_(Registration.year == fy_year, Registration.month >= 4),
        and_(Registration.year == fy_year + 1, Registration.month <= 3),
    )


@router.get("/{state_code}/list")
async def get_rtos_for_state(
    state_code: str = Depends(require_state_code),
    year: int = Query(..., description="Financial year start (April `year` - March `year+1`)"),
    db: AsyncSession = Depends(get_db),
):
    """RTOs with real registration data for this state/FY, ranked by
    volume. Reads from `registrations` directly (not the `rtos` master
    table) so the list only ever shows RTOs that actually have data.
    """
    cache_key = (state_code, year)
    cached = _rto_list_cache.get(cache_key)
    if cached is not None:
        return cached

    query = exclude_supplementary(
        select(
            Registration.rto_code,
            Registration.rto_name,
            func.sum(Registration.count).label("total"),
        )
        .where(Registration.state_code == state_code, fy_filter(year))
    ).group_by(Registration.rto_code, Registration.rto_name).order_by(desc("total"))

    result = await db.execute(query)
    response = [
        {"rto_code": r.rto_code, "rto_name": r.rto_name, "total": r.total}
        for r in result.all()
    ]
    _rto_list_cache.set(cache_key, response)
    return response


@router.get("/{rto_code}/analysis")
async def get_rto_analysis(
    rto_code: str = Depends(require_rto_code),
    year: int = Query(..., description="Financial year start (April `year` - March `year+1`)"),
    db: AsyncSession = Depends(get_db),
):
    """Company (maker) % breakdown for one RTO/FY, plus an overview:
    total registrations and average per active month.
    """
    cache_key = (rto_code, year)
    cached = _rto_analysis_cache.get(cache_key)
    if cached is not None:
        return cached

    base = exclude_supplementary(
        select(Registration).where(Registration.rto_code == rto_code, fy_filter(year))
    )

    maker_query = exclude_supplementary(
        select(Registration.maker, func.sum(Registration.count).label("count"))
        .where(Registration.rto_code == rto_code, fy_filter(year))
    ).group_by(Registration.maker).order_by(desc("count"))

    overview_query = exclude_supplementary(
        select(
            func.sum(Registration.count).label("total"),
            func.count(func.distinct(Registration.month)).label("months_with_data"),
        ).where(Registration.rto_code == rto_code, fy_filter(year))
    )

    maker_result = await db.execute(maker_query)
    makers = maker_result.all()
    total = sum(m.count for m in makers)

    overview_result = await db.execute(overview_query)
    overview_row = overview_result.one()
    months_with_data = overview_row.months_with_data or 0
    avg_monthly = round(total / months_with_data, 1) if months_with_data else 0

    name_result = await db.execute(base.limit(1))
    sample = name_result.scalars().first()

    response = {
        "rto_code": rto_code,
        "rto_name": sample.rto_name if sample else None,
        "state_name": sample.state_name if sample else None,
        "year": year,
        "total": total,
        "avg_monthly": avg_monthly,
        "months_with_data": months_with_data,
        "makers": [
            {
                "maker": m.maker,
                "count": m.count,
                "share_percent": round(m.count / total * 100, 2) if total else 0,
            }
            for m in makers
        ],
    }
    _rto_analysis_cache.set(cache_key, response)
    return response
