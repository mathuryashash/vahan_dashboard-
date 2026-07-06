from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.models import Zone, State, District, RTO, RTODistrict
from app.schemas.schemas import ZoneSchema, StateSchema, DistrictSchema, RTO as RTOSchema

router = APIRouter()


@router.get("/zones", response_model=list[ZoneSchema])
async def get_zones(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Zone).order_by(Zone.zone_name))
    return [ZoneSchema(zone_code=z.zone_code, zone_name=z.zone_name) for z in result.scalars().all()]


@router.get("/zones/{zone_code}/states", response_model=list[StateSchema])
async def get_states_in_zone(zone_code: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(State).where(State.zone_code == zone_code).order_by(State.state_name)
    )
    return [StateSchema(state_code=s.state_code, state_name=s.state_name) for s in result.scalars().all()]


@router.get("/states/{state_code}/districts", response_model=list[DistrictSchema])
async def get_districts_in_state(state_code: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(District).where(District.state_code == state_code).order_by(District.district_name)
    )
    return [
        DistrictSchema(district_code=d.district_code, district_name=d.district_name, state_code=d.state_code)
        for d in result.scalars().all()
    ]


@router.get("/districts/{district_code}/rtos", response_model=list[RTOSchema])
async def get_rtos_in_district(district_code: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(RTO)
        .join(RTODistrict, RTO.rto_code == RTODistrict.rto_code)
        .where(RTODistrict.district_code == district_code)
        .order_by(RTO.rto_name)
    )
    return [
        RTOSchema(rto_code=r.rto_code, rto_name=r.rto_name, state_code=r.state_code)
        for r in result.scalars().all()
    ]
