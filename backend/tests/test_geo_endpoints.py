from app.models.models import State, Zone, District, RTO, RTODistrict


async def _seed_minimal(db_session):
    db_session.add(Zone(zone_code="SOUTH", zone_name="Southern Zone"))
    db_session.add(State(state_code="AP", state_name="Andhra Pradesh", zone_code="SOUTH"))
    db_session.add(District(district_code="AP-GUNTUR", district_name="Guntur", state_code="AP"))
    db_session.add(RTO(rto_code="AP07", rto_name="Guntur", state_code="AP"))
    db_session.add(RTODistrict(rto_code="AP07", district_code="AP-GUNTUR"))
    await db_session.commit()


async def test_list_zones(client, db_session):
    await _seed_minimal(db_session)
    response = await client.get("/api/v1/geo/zones")
    assert response.status_code == 200
    codes = [z["zone_code"] for z in response.json()]
    assert "SOUTH" in codes


async def test_states_in_zone(client, db_session):
    await _seed_minimal(db_session)
    response = await client.get("/api/v1/geo/zones/SOUTH/states")
    assert response.status_code == 200
    assert response.json() == [{"state_code": "AP", "state_name": "Andhra Pradesh"}]


async def test_districts_in_state(client, db_session):
    await _seed_minimal(db_session)
    response = await client.get("/api/v1/geo/states/AP/districts")
    assert response.status_code == 200
    assert response.json() == [{"district_code": "AP-GUNTUR", "district_name": "Guntur", "state_code": "AP"}]


async def test_rtos_in_district(client, db_session):
    await _seed_minimal(db_session)
    response = await client.get("/api/v1/geo/districts/AP-GUNTUR/rtos")
    assert response.status_code == 200
    assert response.json() == [{"rto_code": "AP07", "rto_name": "Guntur", "state_code": "AP"}]
