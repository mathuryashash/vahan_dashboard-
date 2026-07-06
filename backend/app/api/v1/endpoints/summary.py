from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from app.core.database import get_db
from app.models.models import Registration
from app.schemas.schemas import DashboardKPIs
from app.core.config import settings

router = APIRouter()


@router.get("/kpis", response_model=DashboardKPIs)
async def get_dashboard_kpis(
    year: int | None = None,
    month: int | None = None,
    state: str | None = None,
    vehicle_class: str | None = None,
    maker: str | None = None,
    vehicle_model: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    current_year = year or 2026
    prev_year = current_year - 1

    # Base queries for current vs previous periods
    q_current = select(func.sum(Registration.count)).where(Registration.year == current_year)
    q_prev = select(func.sum(Registration.count)).where(Registration.year == prev_year)

    # Apply filters to current and previous queries
    if state:
        q_current = q_current.where(Registration.state_name == state)
        q_prev = q_prev.where(Registration.state_name == state)
    if month:
        q_current = q_current.where(Registration.month == month)
        q_prev = q_prev.where(Registration.month == month)
    if vehicle_class:
        q_current = q_current.where(Registration.vehicle_class == vehicle_class)
        q_prev = q_prev.where(Registration.vehicle_class == vehicle_class)
    if maker:
        q_current = q_current.where(Registration.maker == maker)
        q_prev = q_prev.where(Registration.maker == maker)
    if vehicle_model:
        q_current = q_current.where(Registration.vehicle_model == vehicle_model)
        q_prev = q_prev.where(Registration.vehicle_model == vehicle_model)

    result_current = await db.execute(q_current)
    total_this_period = result_current.scalar() or 0

    result_prev = await db.execute(q_prev)
    total_prev_period = result_prev.scalar() or 0

    # Calculate YoY Growth
    yoy_growth = 0.0
    if total_prev_period > 0:
        yoy_growth = round(
            ((total_this_period - total_prev_period) / total_prev_period) * 100, 2
        )

    # Top State Query
    q_top_state = (
        select(Registration.state_name, func.sum(Registration.count).label("total"))
        .where(Registration.year == current_year)
    )
    if month:
        q_top_state = q_top_state.where(Registration.month == month)
    if state:
        q_top_state = q_top_state.where(Registration.state_name == state)
    if vehicle_class:
        q_top_state = q_top_state.where(Registration.vehicle_class == vehicle_class)
    if maker:
        q_top_state = q_top_state.where(Registration.maker == maker)
    if vehicle_model:
        q_top_state = q_top_state.where(Registration.vehicle_model == vehicle_model)

    q_top_state = q_top_state.group_by(Registration.state_name).order_by(desc("total")).limit(1)
    result_top = await db.execute(q_top_state)
    top_row = result_top.first()
    top_state = top_row[0] if top_row else "N/A"
    top_state_count = top_row[1] if top_row else 0

    # Today's Registrations (or latest day count)
    # Find max day in database for selected month/year
    q_max_day = select(func.max(Registration.day)).where(
        Registration.year == current_year,
        Registration.day.isnot(None)
    )
    if month:
        q_max_day = q_max_day.where(Registration.month == month)
    
    result_max_day = await db.execute(q_max_day)
    max_day = result_max_day.scalar()

    if max_day:
        q_today = select(func.sum(Registration.count)).where(
            Registration.year == current_year,
            Registration.day == max_day
        )
        if month:
            q_today = q_today.where(Registration.month == month)
        if state:
            q_today = q_today.where(Registration.state_name == state)
        if vehicle_class:
            q_today = q_today.where(Registration.vehicle_class == vehicle_class)
        if maker:
            q_today = q_today.where(Registration.maker == maker)
        if vehicle_model:
            q_today = q_today.where(Registration.vehicle_model == vehicle_model)
            
        result_today = await db.execute(q_today)
        total_today = result_today.scalar() or 0
    else:
        # Fallback to daily average of the period
        total_today = int(total_this_period / 30) if total_this_period > 0 else 0

    last_updated = settings.LAST_UPDATED

    return DashboardKPIs(
        total_registrations_today=total_today,
        total_this_month=total_this_period,
        yoy_growth_percent=yoy_growth,
        top_state=top_state,
        top_state_count=top_state_count,
        last_updated=last_updated,
    )


@router.get("/trend")
async def get_trend(
    year: int = 2026,
    month: int | None = None,
    state: str | None = None,
    vehicle_class: str | None = None,
    maker: str | None = None,
    vehicle_model: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    # If a specific month is selected and contains day-wise data (May/June 2026 have daily records)
    # We group by day. Otherwise, group by month.
    is_daily_view = (month is not None)

    if is_daily_view:
        query = select(
            Registration.day, func.sum(Registration.count).label("count")
        ).where(
            Registration.year == year,
            Registration.month == month,
            Registration.day.isnot(None)
        )
        if state:
            query = query.where(Registration.state_name == state)
        if vehicle_class:
            query = query.where(Registration.vehicle_class == vehicle_class)
        if maker:
            query = query.where(Registration.maker == maker)
        if vehicle_model:
            query = query.where(Registration.vehicle_model == vehicle_model)

        query = query.group_by(Registration.day).order_by(Registration.day)
        result = await db.execute(query)
        rows = result.all()
        return [{"day": r[0], "count": r[1]} for r in rows]
    else:
        query = select(
            Registration.month, func.sum(Registration.count).label("count")
        ).where(Registration.year == year)
        if state:
            query = query.where(Registration.state_name == state)
        if vehicle_class:
            query = query.where(Registration.vehicle_class == vehicle_class)
        if maker:
            query = query.where(Registration.maker == maker)
        if vehicle_model:
            query = query.where(Registration.vehicle_model == vehicle_model)

        query = query.group_by(Registration.month).order_by(Registration.month)
        result = await db.execute(query)
        rows = result.all()
        return [{"month": r[0], "count": r[1]} for r in rows]


@router.get("/state-ranking")
async def get_state_ranking(
    year: int = 2026,
    month: int | None = None,
    state: str | None = None,
    vehicle_class: str | None = None,
    maker: str | None = None,
    vehicle_model: str | None = None,
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
):
    query = select(
        Registration.state_name, func.sum(Registration.count).label("total")
    ).where(Registration.year == year)

    if month:
        query = query.where(Registration.month == month)
    if state:
        query = query.where(Registration.state_name == state)
    if vehicle_class:
        query = query.where(Registration.vehicle_class == vehicle_class)
    if maker:
        query = query.where(Registration.maker == maker)
    if vehicle_model:
        query = query.where(Registration.vehicle_model == vehicle_model)

    query = query.group_by(Registration.state_name).order_by(desc("total")).limit(limit)
    result = await db.execute(query)
    rows = result.all()

    total_all = sum(r[1] for r in rows)
    return [
        {
            "state_name": r[0],
            "total_count": r[1],
            "share_percent": round((r[1] / total_all * 100) if total_all > 0 else 0, 2),
        }
        for r in rows
    ]
