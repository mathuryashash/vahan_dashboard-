from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.models.models import Registration

router = APIRouter()


@router.get("/states")
async def compare_states(
    state_a: str,
    state_b: str | None = None,
    year: int = 2026,
    db: AsyncSession = Depends(get_db),
):
    result_a = await db.execute(
        select(Registration.month, func.sum(Registration.count).label("count"))
        .where(Registration.year == year, Registration.state_name == state_a)
        .group_by(Registration.month)
        .order_by(Registration.month)
    )
    rows_a = result_a.all()

    result_b = (
        await db.execute(
            select(Registration.month, func.sum(Registration.count).label("count"))
            .where(Registration.year == year, Registration.state_name == state_b)
            .group_by(Registration.month)
            .order_by(Registration.month)
        )
        if state_b
        else None
    )
    rows_b = result_b.all() if result_b else []

    return {
        "state_a": state_a,
        "state_b": state_b,
        "year": year,
        "state_a_data": [{"month": r[0], "count": r[1]} for r in rows_a],
        "state_b_data": [{"month": r[0], "count": r[1]} for r in rows_b]
        if rows_b
        else [],
    }


@router.get("/all-states")
async def get_all_states_comparison(
    year: int = 2026, limit: int = 36, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Registration.state_name, func.sum(Registration.count).label("total"))
        .where(Registration.year == year)
        .group_by(Registration.state_name)
        .order_by(func.sum(Registration.count).desc())
        .limit(limit)
    )
    rows = result.all()
    total = sum(r[1] for r in rows)
    return [
        {
            "state_name": r[0],
            "count": r[1],
            "share_percent": round((r[1] / total * 100) if total > 0 else 0, 2),
        }
        for r in rows
    ]
