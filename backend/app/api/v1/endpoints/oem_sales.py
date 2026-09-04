from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.models import OEMMonthlySales, User

router = APIRouter()

STALE_AFTER_DAYS = 14


@router.get("/status")
async def get_oem_status(db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)):
    """When FADA data was last actually ingested, so the frontend can warn
    "this is N days old" instead of silently presenting old numbers as
    current -- FADA publishes monthly, so some staleness is normal, but the
    page shouldn't imply data is fresher than it is.

    The age is computed by Postgres itself (func.now() - max(scraped_at)),
    not by comparing the DB value against Python's datetime.now(timezone.utc)
    -- scraped_at is written via the DB-side func.now() default, and this
    Postgres instance's session timezone is Asia/Calcutta (confirmed via
    `SHOW timezone`), so it stores IST wall-clock time into a timezone-naive
    column, not UTC like the rest of this app's own Python-side datetimes
    do. Comparing that against a true-UTC Python `now` was off by the
    UTC+5:30 gap (days_stale came back negative for data ingested minutes
    earlier). Subtracting entirely within Postgres cancels the ambiguity
    out: both sides of the subtraction use the same (mis)interpretation, so
    the difference is correct regardless of what timezone the server
    actually thinks it's in.
    """
    row = (await db.execute(
        select(
            func.max(OEMMonthlySales.scraped_at).label("last"),
            (func.now() - func.max(OEMMonthlySales.scraped_at)).label("age"),
        )
    )).first()
    if row is None or row.last is None:
        return {"last_ingested_at": None, "days_stale": None, "is_stale": True}
    days_stale = row.age.days
    return {
        "last_ingested_at": row.last.isoformat(),
        "days_stale": days_stale,
        "is_stale": days_stale > STALE_AFTER_DAYS,
    }


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
