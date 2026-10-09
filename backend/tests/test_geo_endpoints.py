from app.models.models import State, Zone, District, RTO, RTODistrict, Registration


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


async def test_districts_filtered_to_those_with_data_in_the_financial_year(client, db_session):
    """With ?year=, only districts that resolve to registration data in that FY
    are offered -- otherwise picking one dead-ends in an empty RTO list.

    Guntur's RTO has data in May 2026 (FY 2026-27). Krishna's RTO has data only
    in February 2026, which belongs to FY 2025-26, so the FY boundary decides
    whether Krishna appears -- the part of this most likely to go subtly wrong.
    """
    await _seed_minimal(db_session)
    await db_session.merge(District(district_code="AP-KRISHNA", district_name="Krishna", state_code="AP"))
    await db_session.merge(RTO(rto_code="AP16", rto_name="Vijayawada", state_code="AP"))
    await db_session.merge(RTODistrict(rto_code="AP16", district_code="AP-KRISHNA"))
    await db_session.commit()
    db_session.add_all([
        Registration(state_code="AP", state_name="Andhra Pradesh", rto_code="AP07",
                     year=2026, month=5, vehicle_class="All", maker="M", count=10),
        Registration(state_code="AP", state_name="Andhra Pradesh", rto_code="AP16",
                     year=2026, month=2, vehicle_class="All", maker="M", count=10),
    ])
    await db_session.commit()

    def names(response):
        assert response.status_code == 200
        return [d["district_name"] for d in response.json()]

    # No year: unchanged behaviour, every district in the state.
    assert names(await client.get("/api/v1/geo/states/AP/districts")) == ["Guntur", "Krishna"]
    # FY 2026-27: Feb 2026 falls in the previous FY, so Krishna has nothing.
    assert names(await client.get("/api/v1/geo/states/AP/districts?year=2026")) == ["Guntur"]
    # FY 2025-26 (Apr 2025 - Mar 2026) is exactly where Krishna's data sits.
    assert names(await client.get("/api/v1/geo/states/AP/districts?year=2025")) == ["Krishna"]


async def test_rtos_in_district(client, db_session):
    await _seed_minimal(db_session)
    response = await client.get("/api/v1/geo/districts/AP-GUNTUR/rtos")
    assert response.status_code == 200
    assert response.json() == [{"rto_code": "AP07", "rto_name": "Guntur", "state_code": "AP"}]
