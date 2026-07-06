from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.models import State, RTO
from app.schemas.schemas import StateSchema

router = APIRouter()


@router.get("/", response_model=list[StateSchema])
async def get_all_states(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(State).order_by(State.state_name))
    rows = result.scalars().all()
    return [
        StateSchema(state_code=str(r.state_code), state_name=str(r.state_name))
        for r in rows
    ]


@router.get("/{state_code}/rtos")
async def get_rtos_by_state(state_code: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(RTO).where(RTO.state_code == state_code).order_by(RTO.rto_name)
    )
    rows = result.scalars().all()
    return [
        {"rto_code": r.rto_code, "rto_name": r.rto_name, "state_code": r.state_code}
        for r in rows
    ]
