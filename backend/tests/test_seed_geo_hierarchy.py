import io
import pytest
from sqlalchemy import select
from app.scripts.seed_geo_hierarchy import seed_from_rows
from app.models.models import State, Zone, District, RTO, RTODistrict

SAMPLE_ROWS = [
    {"RegNo": "AP01", "Place": "Adilabad / Mancherial / Nirmal", "State": "Andhra Pradesh"},
    {"RegNo": "MH12", "Place": "Pune", "State": "Maharashtra"},
    {"RegNo": "OR05", "Place": "Cuttack, Jagatsinghpur", "State": "Orissa"},
]


async def test_seed_creates_zones_states_districts_rtos(db_session):
    db_session.add(State(state_code="AP", state_name="Andhra Pradesh"))
    db_session.add(State(state_code="MH", state_name="Maharashtra"))
    db_session.add(State(state_code="OD", state_name="Odisha"))
    db_session.add(State(state_code="LD", state_name="Ladakh"))
    db_session.add(State(state_code="LA", state_name="Lakshadweep"))
    await db_session.commit()

    await seed_from_rows(db_session, SAMPLE_ROWS)

    zones = (await db_session.execute(select(Zone))).scalars().all()
    assert len(zones) == 6

    ap_state = (await db_session.execute(select(State).where(State.state_code == "AP"))).scalar_one()
    assert ap_state.zone_code == "SOUTH"

    districts = (await db_session.execute(select(District).where(District.state_code == "AP"))).scalars().all()
    assert {d.district_name for d in districts} == {"Adilabad", "Mancherial", "Nirmal"}

    rto = (await db_session.execute(select(RTO).where(RTO.rto_code == "AP01"))).scalar_one()
    assert rto.state_code == "AP"

    links = (await db_session.execute(select(RTODistrict).where(RTODistrict.rto_code == "AP01"))).scalars().all()
    assert len(links) == 3

    or_rto = (await db_session.execute(select(RTO).where(RTO.rto_code == "OR05"))).scalar_one()
    assert or_rto.state_code == "OD"


async def test_seed_fixes_ladakh_lakshadweep_name_swap(db_session):
    db_session.add(State(state_code="LD", state_name="Ladakh"))
    db_session.add(State(state_code="LA", state_name="Lakshadweep"))
    await db_session.commit()

    await seed_from_rows(db_session, [])

    ld = (await db_session.execute(select(State).where(State.state_code == "LD"))).scalar_one()
    la = (await db_session.execute(select(State).where(State.state_code == "LA"))).scalar_one()
    assert ld.state_name == "Lakshadweep"
    assert la.state_name == "Ladakh"


async def test_seed_is_idempotent(db_session):
    db_session.add(State(state_code="MH", state_name="Maharashtra"))
    await db_session.commit()

    await seed_from_rows(db_session, SAMPLE_ROWS)
    await seed_from_rows(db_session, SAMPLE_ROWS)  # run twice

    rtos = (await db_session.execute(select(RTO))).scalars().all()
    assert len([r for r in rtos if r.rto_code == "MH12"]) == 1


async def test_seed_skips_malformed_compound_rto_codes(db_session):
    db_session.add(State(state_code="AP", state_name="Andhra Pradesh"))
    await db_session.commit()

    rows = SAMPLE_ROWS + [
        {"RegNo": "AP16 & AP17", "Place": "Bejawada / Gudivada", "State": "Andhra Pradesh"},
    ]
    await seed_from_rows(db_session, rows)

    rtos = (await db_session.execute(select(RTO))).scalars().all()
    assert "AP16 & AP17" not in {r.rto_code for r in rtos}
    # the well-formed rows in the same batch still get seeded
    assert "AP01" in {r.rto_code for r in rtos}
