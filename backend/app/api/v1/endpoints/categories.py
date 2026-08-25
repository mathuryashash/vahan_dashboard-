from datetime import datetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from app.core.database import get_db
from app.core.query_filters import apply_common_filters, fuel_category, fuel_group, latest_month_with_data
from app.models.models import MakerCategoryTotal, Registration

router = APIRouter()

_DEFAULT_YEAR = datetime.now().year


@router.get("/")
async def get_categories(
    year: int = _DEFAULT_YEAR,
    month: int | None = None,
    state: str | None = None,
    maker: str | None = None,
    vehicle_model: str | None = None,
    raw: bool = False,
    db: AsyncSession = Depends(get_db)
):
    # vehicle_class='All' is the placeholder used by real scraped rows that
    # don't carry class info at that pivot (the maker- and fuel-dimension
    # passes -- see Registration.is_supplementary). Excluding it here means
    # this breakdown only reflects rows that actually have a real class:
    # synthetic data (always did) and the vehicle_class-dimension real pass.
    #
    # Groups by the broad vehicle_category by default (2W/3W/4W/Commercial/
    # Other -- see query_filters.classify_vehicle); ?raw=true groups by the
    # original 89-value vehicle_class instead, for anyone who wants the
    # granular view.
    group_col = Registration.vehicle_class if raw else Registration.vehicle_category
    q_curr = (
        select(group_col, func.sum(Registration.count).label("total"))
        .where(Registration.year == year, Registration.vehicle_class != "All")
    )
    q_prev = (
        select(group_col, func.sum(Registration.count).label("total"))
        .where(Registration.year == year - 1, Registration.vehicle_class != "All")
    )

    # When no specific month is requested, compare year-to-date rather than
    # full calendar year vs full calendar year (see summary.py get_dashboard_kpis
    # for the same fix and full rationale): cap both years at the latest month
    # that actually has data for `year`, so a partially-populated current year
    # isn't compared against a fully-populated prior year.
    compare_month = month
    if compare_month is None:
        compare_month = await latest_month_with_data(db, year)

    if month:
        q_curr = q_curr.where(Registration.month == month)
        q_prev = q_prev.where(Registration.month == month)
    elif compare_month:
        q_curr = q_curr.where(Registration.month <= compare_month)
        q_prev = q_prev.where(Registration.month <= compare_month)
    q_curr = apply_common_filters(q_curr, state=state, maker=maker, vehicle_model=vehicle_model)
    q_prev = apply_common_filters(q_prev, state=state, maker=maker, vehicle_model=vehicle_model)

    q_curr = q_curr.group_by(group_col).order_by(desc("total"))
    q_prev = q_prev.group_by(group_col)

    result = await db.execute(q_curr)
    rows = result.all()
    total = sum(r[1] for r in rows)

    prev_result = await db.execute(q_prev)
    prev_rows = {r[0]: r[1] for r in prev_result.all()}

    key_name = "vehicle_class" if raw else "vehicle_category"
    return [
        {
            key_name: r[0],
            "total_count": r[1],
            "share_percent": round((r[1] / total * 100) if total > 0 else 0, 2),
            "prev_count": prev_rows.get(r[0], 0),
            "yoy_growth": round(
                ((r[1] - prev_rows.get(r[0], 0)) / prev_rows.get(r[0], 1) * 100), 2
            )
            if prev_rows.get(r[0], 0) > 0
            else 0.0,
        }
        for r in rows
    ]


@router.get("/top-makers")
async def get_top_makers(
    vehicle_class: str | None = None,
    vehicle_category: str | None = None,
    commercial_tier: str | None = None,
    year: int = _DEFAULT_YEAR,
    month: int | None = None,
    state: str | None = None,
    vehicle_model: str | None = None,
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
):
    query = select(
        Registration.maker, func.sum(Registration.count).label("total")
    ).where(Registration.year == year, Registration.maker.isnot(None))

    if month:
        query = query.where(Registration.month == month)
    query = apply_common_filters(
        query, state=state, vehicle_class=vehicle_class, vehicle_category=vehicle_category,
        commercial_tier=commercial_tier, vehicle_model=vehicle_model,
    )

    query = query.group_by(Registration.maker).order_by(desc("total")).limit(limit)

    result = await db.execute(query)
    rows = result.all()
    return [{"maker": r[0], "count": r[1]} for r in rows]


@router.get("/fuel-breakdown")
async def get_fuel_breakdown(
    vehicle_class: str | None = None,
    vehicle_category: str | None = None,
    commercial_tier: str | None = None,
    fuel_group_filter: str | None = Query(None, alias="fuel_group"),
    year: int = _DEFAULT_YEAR,
    month: int | None = None,
    state: str | None = None,
    maker: str | None = None,
    vehicle_model: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(
        Registration.fuel_type, func.sum(Registration.count).label("total")
    ).where(Registration.year == year, Registration.fuel_type.isnot(None))

    if month:
        query = query.where(Registration.month == month)
    query = apply_common_filters(
        query, state=state, vehicle_class=vehicle_class, vehicle_category=vehicle_category,
        commercial_tier=commercial_tier, maker=maker, vehicle_model=vehicle_model,
    )

    query = query.group_by(Registration.fuel_type)

    # Grouped in Python, not SQL: VAHAN's raw fuel_type is a specific
    # powertrain/fuel-system string (e.g. "PETROL/HYBRID/CNG"), not the
    # handful of categories people actually want to compare -- see
    # fuel_category's docstring. Re-aggregating ~37 already-summed rows in
    # Python is negligible cost next to the query itself, and keeps the
    # bucket rules in one plain-Python place instead of a SQL CASE
    # expression that has to be kept in sync with it by hand.
    result = await db.execute(query)
    totals: dict[str, int] = {}
    for raw_fuel_type, total in result.all():
        if fuel_group_filter and fuel_group(raw_fuel_type) != fuel_group_filter:
            continue
        bucket = fuel_category(raw_fuel_type)
        totals[bucket] = totals.get(bucket, 0) + total
    return [
        {"fuel_type": bucket, "count": total}
        for bucket, total in sorted(totals.items(), key=lambda item: item[1], reverse=True)
    ]


@router.get("/model-breakdown")
async def get_model_breakdown(
    vehicle_class: str | None = None,
    vehicle_category: str | None = None,
    commercial_tier: str | None = None,
    maker: str | None = None,
    year: int = _DEFAULT_YEAR,
    month: int | None = None,
    state: str | None = None,
    limit: int = 15,
    db: AsyncSession = Depends(get_db),
):
    query = select(
        Registration.vehicle_model, func.sum(Registration.count).label("total")
    ).where(
        Registration.year == year,
        Registration.vehicle_model.isnot(None),
        Registration.vehicle_model != ""
    )

    if month:
        query = query.where(Registration.month == month)
    query = apply_common_filters(
        query, state=state, vehicle_class=vehicle_class, vehicle_category=vehicle_category,
        commercial_tier=commercial_tier, maker=maker,
    )

    query = query.group_by(Registration.vehicle_model).order_by(desc("total")).limit(limit)

    result = await db.execute(query)
    rows = result.all()

    total = sum(r[1] for r in rows)
    return [
        {
            "model": r[0],
            "count": r[1],
            "share_percent": round((r[1] / total * 100) if total > 0 else 0, 2),
        }
        for r in rows
    ]


@router.get("/maker-category-breakdown")
async def get_maker_category_breakdown(
    year: int = _DEFAULT_YEAR,
    state: str | None = None,
    vehicle_category: str | None = None,
    maker: str | None = None,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """Real Maker x Vehicle Category totals -- year-only, no month
    breakdown exists in this pivot at all (see MakerCategoryTotal's
    docstring). Groups by whichever of maker/vehicle_category is left
    unfixed: pass vehicle_category to rank makers within it, or pass maker
    to rank its categories. If both are given, groups by maker (returns the
    single row matching both).
    """
    group_col = MakerCategoryTotal.vehicle_category if maker else MakerCategoryTotal.maker
    query = select(group_col, func.sum(MakerCategoryTotal.count).label("total")).where(
        MakerCategoryTotal.year == year
    )
    if state:
        query = query.where(MakerCategoryTotal.state_name == state)
    if vehicle_category:
        query = query.where(MakerCategoryTotal.vehicle_category == vehicle_category)
    if maker:
        query = query.where(MakerCategoryTotal.maker == maker)

    query = query.group_by(group_col).order_by(desc("total")).limit(limit)
    result = await db.execute(query)
    rows = result.all()

    key_name = "vehicle_category" if maker else "maker"
    return [{key_name: r[0], "count": r[1]} for r in rows]
