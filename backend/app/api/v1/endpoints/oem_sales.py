from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.models import OEMMonthlySales, User

router = APIRouter()


@router.get("/categories")
async def get_oem_categories(
    year: int | None = None, db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)
):
    """Categories with real FADA data. Filtered to `year` when given, so the
    dropdown doesn't offer a category (e.g. one FADA only started breaking
    out in 2024) that has zero rows for whatever year is currently selected
    -- that combination always rendered as an empty "No FADA data" state,
    which reads as broken rather than as an honest "nothing published yet."
    """
    query = select(OEMMonthlySales.category).distinct()
    if year is not None:
        query = query.where(OEMMonthlySales.year == year)
    result = await db.execute(query)
    return [row[0] for row in result.all()]


@router.get("/monthly")
async def get_oem_monthly(
    category: str,
    year: int,
    month: int | None = None,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    if month is not None:
        query = (
            select(OEMMonthlySales)
            .where(
                OEMMonthlySales.category == category,
                OEMMonthlySales.year == year,
                OEMMonthlySales.month == month,
            )
            .order_by(desc(OEMMonthlySales.count))
        )
        result = await db.execute(query)
        rows = result.scalars().all()
        return [
            {"maker": r.maker, "count": r.count, "share_percent": r.share_percent}
            for r in rows
        ]

    # No month picked: a year-to-date leaderboard, summed across every real
    # month FADA has published so far this year. share_percent isn't
    # meaningful summed across months (they're each relative to a different
    # month's total market), so it's omitted rather than shown misleadingly.
    query = (
        select(OEMMonthlySales.maker, func.sum(OEMMonthlySales.count).label("count"))
        .where(
            OEMMonthlySales.category == category,
            OEMMonthlySales.year == year,
            OEMMonthlySales.month.isnot(None),
        )
        .group_by(OEMMonthlySales.maker)
        .order_by(desc("count"))
    )
    result = await db.execute(query)
    return [
        {"maker": maker, "count": count, "share_percent": None}
        for maker, count in result.all()
    ]


@router.get("/trend")
async def get_oem_trend(
    maker: str,
    category: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    query = (
        select(OEMMonthlySales)
        .where(OEMMonthlySales.maker == maker, OEMMonthlySales.category == category)
        .order_by(OEMMonthlySales.year, OEMMonthlySales.month)
    )
    result = await db.execute(query)
    rows = result.scalars().all()
    return [
        {"year": r.year, "month": r.month, "count": r.count, "share_percent": r.share_percent}
        for r in rows
    ]
