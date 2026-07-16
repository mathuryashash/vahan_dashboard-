from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from app.core.database import get_db
from app.models.models import OEMMonthlySales

router = APIRouter()


@router.get("/categories")
async def get_oem_categories(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(OEMMonthlySales.category).distinct())
    return [row[0] for row in result.all()]


@router.get("/monthly")
async def get_oem_monthly(
    category: str,
    year: int,
    month: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(OEMMonthlySales).where(
        OEMMonthlySales.category == category,
        OEMMonthlySales.year == year,
    )
    query = query.where(OEMMonthlySales.month.is_(None) if month is None else OEMMonthlySales.month == month)
    query = query.order_by(desc(OEMMonthlySales.count))

    result = await db.execute(query)
    rows = result.scalars().all()
    return [
        {"maker": r.maker, "count": r.count, "share_percent": r.share_percent}
        for r in rows
    ]


@router.get("/trend")
async def get_oem_trend(
    maker: str,
    category: str,
    db: AsyncSession = Depends(get_db),
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
