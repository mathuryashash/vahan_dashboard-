from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import exists, select
from app.api.v1.endpoints.rto import fy_filter
from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.models import Zone, State, District, RTO, RTODistrict, Registration, User
from app.schemas.schemas import ZoneSchema, StateSchema, DistrictSchema, RTO as RTOSchema

router = APIRouter()


@router.get("/zones", response_model=list[ZoneSchema])
async def get_zones(db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)):
    result = await db.execute(select(Zone).order_by(Zone.zone_name))
    return [ZoneSchema(zone_code=z.zone_code, zone_name=z.zone_name) for z in result.scalars().all()]


@router.get("/zones/{zone_code}/states", response_model=list[StateSchema])
async def get_states_in_zone(zone_code: str, db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)):
    result = await db.execute(
        select(State).where(State.zone_code == zone_code).order_by(State.state_name)
    )
    return [StateSchema(state_code=s.state_code, state_name=s.state_name) for s in result.scalars().all()]


@router.get("/states/{state_code}/districts", response_model=list[DistrictSchema])
async def get_districts_in_state(
    state_code: str,
    year: int | None = Query(None, description="Financial year; when given, only districts that have registration data in it"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    query = select(District).where(District.state_code == state_code)
    if year is not None:
        # Offer only districts we can actually resolve to data. The district
        # -> RTO mapping (rto_districts) is keyed on NUMBER-PLATE series from
        # a reference dataset ("AP01"), while registrations carry VAHAN's own
        # office codes ("AP102", "TG1"). They are different numbering schemes,
        # not two spellings of one, and the reference also predates the Odisha
        # (OR->OD), Uttarakhand (UA->UK), Telangana (2014) and Ladakh (2019)
        # reorganisations -- so ~35% of districts map to no RTO with data, and
        # picking one showed an empty list that read as "no registrations
        # here". Hiding them is deliberate: deriving the missing links from the
        # code pattern was measured and rejected -- it resolves 75% but maps
        # e.g. Punganur (Chittoor) to Hyderabad, and a confidently wrong
        # district is worse than an absent one. Every RTO stays reachable via
        # the state-wide "All Districts" view. The real fix is a curated
        # VAHAN-code -> district reference.
        # Year-aware, not "data in any year": early in a new FY almost no
        # district has data yet, and an any-year filter would offer them all.
        query = query.where(exists(
            select(1).select_from(RTODistrict)
            .join(Registration, Registration.rto_code == RTODistrict.rto_code)
            .where(RTODistrict.district_code == District.district_code, fy_filter(year))
        ))
    result = await db.execute(query.order_by(District.district_name))
    return [
        DistrictSchema(district_code=d.district_code, district_name=d.district_name, state_code=d.state_code)
        for d in result.scalars().all()
    ]


@router.get("/districts/{district_code}/rtos", response_model=list[RTOSchema])
async def get_rtos_in_district(district_code: str, db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)):
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
