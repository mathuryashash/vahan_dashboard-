from app.models.models import State, Zone, District, RTO, RTODistrict


async def _seed_minimal(db_session):
    # merge (not add) -- with no relationship() between these models,
    # plain add()+commit doesn't order cross-table INSERTs by FK dependency,
    # so a child row can be sent before its still-pending parent. merge()
    # writes each row immediately, keeping this chain in dependency order.
    await db_session.merge(Zone(zone_code="SOUTH", zone_name="Southern Zone"))
    await db_session.merge(State(state_code="AP", state_name="Andhra Pradesh", zone_code="SOUTH"))
    await db_session.merge(District(district_code="AP-GUNTUR", district_name="Guntur", state_code="AP"))
    await db_session.merge(RTO(rto_code="AP07", rto_name="Guntur", state_code="AP"))
    await db_session.merge(RTODistrict(rto_code="AP07", district_code="AP-GUNTUR"))
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
