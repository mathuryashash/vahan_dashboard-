from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.models.models import Registration

router = APIRouter()


@router.get("/monthly")
async def get_yoy_monthly(
    year_a: int = Query(default=2025),
    year_b: int = Query(default=2026),
    state: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    query_a = (
        select(Registration.month, func.sum(Registration.count).label("count"))
        .where(Registration.year == year_a)
        .group_by(Registration.month)
    )

    query_b = (
        select(Registration.month, func.sum(Registration.count).label("count"))
        .where(Registration.year == year_b)
        .group_by(Registration.month)
    )

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
        b = rows_b.get(m, 0)
        growth = round(((b - a) / a * 100), 2) if a > 0 else 0.0
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
    year_a: int = Query(default=2025),
    year_b: int = Query(default=2026),
    db: AsyncSession = Depends(get_db),
):
    result_a = await db.execute(
        select(func.sum(Registration.count)).where(Registration.year == year_a)
    )
    result_b = await db.execute(
        select(func.sum(Registration.count)).where(Registration.year == year_b)
    )

    total_a = result_a.scalar() or 0
    total_b = result_b.scalar() or 0
    growth = round(((total_b - total_a) / total_a * 100), 2) if total_a > 0 else 0.0

    return {
        f"total_{year_a}": total_a,
        f"total_{year_b}": total_b,
        "growth_percent": growth,
    }
