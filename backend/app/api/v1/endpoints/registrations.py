from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.core.query_filters import apply_total_filters
from app.core.scope import get_effective_state, scoped_category, scoped_rto
from app.models.models import Registration
from app.schemas.schemas import MonthCount, RegistrationOut

router = APIRouter()


@router.get("/", response_model=list[RegistrationOut])
async def get_registrations(
    state: str | None = Depends(get_effective_state),
    year: int | None = None,
    month: int | None = None,
    day: int | None = None,
    vehicle_class: str | None = None,
    maker: str | None = None,
    vehicle_model: str | None = None,
    fuel_type: str | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
    user_category: str | None = Depends(scoped_category),
    user_rto: str | None = Depends(scoped_rto),
    db: AsyncSession = Depends(get_db),
):
    query = select(Registration)
    filters = []
    # Raw rows, so this has to be clamped here too -- a category-scoped
    # account asking for vehicle_class='M-CYCLE/SCOOTER' would otherwise get
    # real two-wheeler rows straight out of the table.
    if user_category:
        filters.append(Registration.vehicle_category == user_category)
    if state:
        filters.append(Registration.state_name == state)
    # Raw rows again: get_effective_state only ever clamped an RTO-tier
    # account to its STATE, so this endpoint handed it every other RTO's rows
    # verbatim (byte-identical to the state account's, live-proven).
    if user_rto:
        filters.append(Registration.rto_code == user_rto)
    if year:
        filters.append(Registration.year == year)
    if month:
        filters.append(Registration.month == month)
    if day:
        filters.append(Registration.day == day)
    if vehicle_class:
        filters.append(Registration.vehicle_class == vehicle_class)
    if maker:
        filters.append(Registration.maker == maker)
    if vehicle_model:
        filters.append(Registration.vehicle_model == vehicle_model)
    if fuel_type:
        filters.append(Registration.fuel_type == fuel_type)

    for f in filters:
        query = query.where(f)

    query = query.order_by(Registration.year.desc(), Registration.month.desc()).limit(
        limit
    )

    result = await db.execute(query)
    rows = result.scalars().all()

    return [
        {
            "id": r.id,
            "state_code": r.state_code,
            "state_name": r.state_name,
            "month": r.month,
            "year": r.year,
            "day": r.day,
            "vehicle_class": r.vehicle_class,
            "count": r.count,
            "maker": r.maker,
            "vehicle_model": r.vehicle_model,
            "fuel_type": r.fuel_type,
        }
        for r in rows
    ]


@router.get("/aggregate/by-month", response_model=list[MonthCount])
async def get_aggregate_by_month(
    year: int,
    state: str | None = Depends(get_effective_state),
    user_category: str | None = Depends(scoped_category),
    user_rto: str | None = Depends(scoped_rto),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Registration.month, func.sum(Registration.count).label("total"))
        .where(Registration.year == year)
        .group_by(Registration.month)
        .order_by(Registration.month)
    )

    if state:
        query = query.where(Registration.state_name == state)
    # A bare where, not apply_total_filters: this endpoint deliberately
    # doesn't exclude supplementary rows for unscoped callers (see below), and
    # routing the RTO clamp through apply_total_filters would silently change
    # an RTO account's totals to a different definition than everyone else's.
    # Narrow only.
    if user_rto:
        query = query.where(Registration.rto_code == user_rto)
    # Applied only when actually scoped, so an unscoped caller's totals are
    # byte-for-byte what they were. apply_total_filters (not a bare where)
    # because a category filter has to read the vehicle_class-dimension pass
    # -- the only rows carrying a real category -- and must NOT then also
    # exclude supplementary rows, which would strip out exactly those rows
    # and silently zero the result.
    if user_category:
        query = apply_total_filters(query, vehicle_category=user_category)

    result = await db.execute(query)
    rows = result.all()
    return [{"month": r[0], "count": r[1]} for r in rows]
