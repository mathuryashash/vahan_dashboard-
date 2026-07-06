from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from app.core.database import get_db
from app.models.models import Registration

router = APIRouter()


@router.get("/")
async def get_categories(
    year: int = 2026,
    month: int | None = None,
    state: str | None = None,
    maker: str | None = None,
    vehicle_model: str | None = None,
    db: AsyncSession = Depends(get_db)
):
    q_curr = (
        select(Registration.vehicle_class, func.sum(Registration.count).label("total"))
        .where(Registration.year == year)
    )
    q_prev = (
        select(Registration.vehicle_class, func.sum(Registration.count).label("total"))
        .where(Registration.year == year - 1)
    )

    # Apply filters
    for q in [q_curr, q_prev]:
        # Wait, since q is immutable, we must update it
        pass

    if state:
        q_curr = q_curr.where(Registration.state_name == state)
        q_prev = q_prev.where(Registration.state_name == state)
    if month:
        q_curr = q_curr.where(Registration.month == month)
        q_prev = q_prev.where(Registration.month == month)
    if maker:
        q_curr = q_curr.where(Registration.maker == maker)
        q_prev = q_prev.where(Registration.maker == maker)
    if vehicle_model:
        q_curr = q_curr.where(Registration.vehicle_model == vehicle_model)
        q_prev = q_prev.where(Registration.vehicle_model == vehicle_model)

    q_curr = q_curr.group_by(Registration.vehicle_class).order_by(desc("total"))
    q_prev = q_prev.group_by(Registration.vehicle_class)

    result = await db.execute(q_curr)
    rows = result.all()
    total = sum(r[1] for r in rows)

    prev_result = await db.execute(q_prev)
    prev_rows = {r[0]: r[1] for r in prev_result.all()}

    return [
        {
            "vehicle_class": r[0],
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
    year: int = 2026,
    month: int | None = None,
    state: str | None = None,
    vehicle_model: str | None = None,
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
):
    query = select(
        Registration.maker, func.sum(Registration.count).label("total")
    ).where(Registration.year == year, Registration.maker.isnot(None))

    if vehicle_class:
        query = query.where(Registration.vehicle_class == vehicle_class)
    if month:
        query = query.where(Registration.month == month)
    if state:
        query = query.where(Registration.state_name == state)
    if vehicle_model:
        query = query.where(Registration.vehicle_model == vehicle_model)

    query = query.group_by(Registration.maker).order_by(desc("total")).limit(limit)

    result = await db.execute(query)
    rows = result.all()
    return [{"maker": r[0], "count": r[1]} for r in rows]


@router.get("/fuel-breakdown")
async def get_fuel_breakdown(
    vehicle_class: str | None = None,
    year: int = 2026,
    month: int | None = None,
    state: str | None = None,
    maker: str | None = None,
    vehicle_model: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(
        Registration.fuel_type, func.sum(Registration.count).label("total")
    ).where(Registration.year == year, Registration.fuel_type.isnot(None))

    if vehicle_class:
        query = query.where(Registration.vehicle_class == vehicle_class)
    if month:
        query = query.where(Registration.month == month)
    if state:
        query = query.where(Registration.state_name == state)
    if maker:
        query = query.where(Registration.maker == maker)
    if vehicle_model:
        query = query.where(Registration.vehicle_model == vehicle_model)

    query = query.group_by(Registration.fuel_type).order_by(desc("total"))

    result = await db.execute(query)
    rows = result.all()
    return [{"fuel_type": r[0], "count": r[1]} for r in rows]


@router.get("/model-breakdown")
async def get_model_breakdown(
    vehicle_class: str | None = None,
    maker: str | None = None,
    year: int = 2026,
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

    if vehicle_class:
        query = query.where(Registration.vehicle_class == vehicle_class)
    if maker:
        query = query.where(Registration.maker == maker)
    if month:
        query = query.where(Registration.month == month)
    if state:
        query = query.where(Registration.state_name == state)

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
