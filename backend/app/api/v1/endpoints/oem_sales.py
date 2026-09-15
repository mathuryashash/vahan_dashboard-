from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.models import OEMMonthlySales, User, VehicleCategoryScope
from app.schemas.schemas import OemMakerShare, OemStatus, OemTrendPoint

router = APIRouter()

STALE_AFTER_DAYS = 14

# FADA labels its own categories ("Two-Wheeler", "PV", "Tractor", ...) and
# has added/renamed them across the archive (see OEMMonthlySales.category) --
# a different vocabulary from the vehicle_category buckets a user is scoped
# to, so the two need an explicit bridge. Aliases are matched
# case-insensitively and anything NOT listed is denied to a scoped account
# rather than defaulted in: a future FADA category nobody has mapped yet
# must not quietly become visible to every segment customer.
_FADA_ALIASES: dict[str, set[str]] = {
    VehicleCategoryScope.TWO_WHEELER: {"two-wheeler", "two wheeler", "2w"},
    VehicleCategoryScope.THREE_WHEELER: {"three-wheeler", "three wheeler", "3w"},
    VehicleCategoryScope.FOUR_WHEELER: {"pv", "passenger vehicle", "passenger vehicles", "four-wheeler"},
    VehicleCategoryScope.COMMERCIAL: {"cv", "commercial vehicle", "commercial vehicles", "lcv", "mcv", "hcv"},
    # The Other bucket's members, checked against the labels actually
    # present in this database: FADA publishes the same construction-
    # equipment table under three spellings across the archive.
    VehicleCategoryScope.OTHER: {
        "tractor", "trac", "ce", "construction equipment",
        "wheeled construction equipment", "wheeled - construction equipment",
    },
}


def _category_allowed(user: User, category: str) -> bool:
    if not user.scope_vehicle_category:
        return True
    return category.strip().lower() in _FADA_ALIASES.get(user.scope_vehicle_category, set())


def _require_category(user: User, category: str) -> None:
    if not _category_allowed(user, category):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail=f"Not permitted to view {category!r} -- this account covers {user.scope_vehicle_category}.",
        )


@router.get("/status", response_model=OemStatus)
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


@router.get("/categories", response_model=list[str])
async def get_oem_categories(
    year: int | None = None, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
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
    # Filtered, not 403'd: this is the IndustrySales page's own dropdown, so
    # a category-scoped account simply never sees the other segments listed.
    return [row[0] for row in result.all() if _category_allowed(user, row[0])]


@router.get("/monthly", response_model=list[OemMakerShare])
async def get_oem_monthly(
    category: str,
    year: int,
    month: int | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # A required param with no "omitted" case to narrow, so a mismatch is a
    # hard 403 -- same shape as require_state_code in app.core.scope.
    _require_category(user, category)
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
    # month FADA has published so far this year. Each row's own
    # share_percent column is a single month's share of that month's total
    # market -- not meaningful summed as-is across months with different
    # totals. What IS meaningful: this maker's YTD count as a share of the
    # YTD total across all makers, so compute that instead of leaving the
    # column blank.
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
    rows = result.all()
    ytd_total = sum(count for _, count in rows)
    return [
        {
            "maker": maker,
            "count": count,
            "share_percent": round(count / ytd_total * 100, 2) if ytd_total else None,
        }
        for maker, count in rows
    ]


@router.get("/trend", response_model=list[OemTrendPoint])
async def get_oem_trend(
    maker: str,
    category: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_category(user, category)
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
