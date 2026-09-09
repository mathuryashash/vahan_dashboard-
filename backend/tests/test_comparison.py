"""Tests for /comparison/states -- the vehicle_category/fuel_group filters
added here need apply_total_filters (not a bare exclude_supplementary), the
same fix summary.py's kpis/trend already needed: the canonical maker-pass
always stores vehicle_class='All' (never a real category), so a naive
exclude_supplementary + vehicle_category filter would silently return zero
rows for every category."""
from app.models.models import Registration


async def _seed_state(db_session, state_name="Delhi", state_code="DL", rto_code="DL1"):
    # Canonical maker-pass: real total, but vehicle_class='All' -- never
    # matches a real vehicle_category filter.
    db_session.add(Registration(
        state_code=state_code, state_name=state_name, rto_code=rto_code, rto_name="Test RTO",
        month=6, year=2026, count=1000, vehicle_class="All", vehicle_category=None,
        maker="HONDA", fuel_type=None, is_supplementary=False,
    ))
    # vehicle_class-dimension pass: the only rows that carry a real category.
    db_session.add(Registration(
        state_code=state_code, state_name=state_name, rto_code=rto_code, rto_name="Test RTO",
        month=6, year=2026, count=300, vehicle_class="MOTOR CAR", vehicle_category="Four-Wheeler",
        maker=None, fuel_type=None, is_supplementary=True,
    ))
    db_session.add(Registration(
        state_code=state_code, state_name=state_name, rto_code=rto_code, rto_name="Test RTO",
        month=6, year=2026, count=700, vehicle_class="M-CYCLE/SCOOTER", vehicle_category="Two-Wheeler",
        maker=None, fuel_type=None, is_supplementary=True,
    ))
    await db_session.commit()


async def test_compare_states_without_category_uses_canonical_total(client, db_session):
    await _seed_state(db_session)
    response = await client.get("/api/v1/comparison/states", params={"state_a": "Delhi", "year": 2026})
    assert response.status_code == 200
    data = response.json()
    assert data["state_a_data"] == [{"month": 6, "count": 1000}]


async def test_compare_states_with_category_reads_the_real_category_rows(client, db_session):
    await _seed_state(db_session)
    response = await client.get(
        "/api/v1/comparison/states",
        params={"state_a": "Delhi", "year": 2026, "vehicle_category": "Four-Wheeler"},
    )
    assert response.status_code == 200
    data = response.json()
    # Must be 300 (the real Four-Wheeler row), not 0 (canonical-pass zeroed
    # out) and not 1300 (double-counted with the canonical pass).
    assert data["state_a_data"] == [{"month": 6, "count": 300}]


async def test_compare_states_category_filter_applies_to_both_states(client, db_session):
    await _seed_state(db_session, state_name="Delhi", state_code="DL", rto_code="DL1")
    await _seed_state(db_session, state_name="Uttar Pradesh", state_code="UP", rto_code="UP1")
    response = await client.get(
        "/api/v1/comparison/states",
        params={"state_a": "Delhi", "state_b": "Uttar Pradesh", "year": 2026, "vehicle_category": "Two-Wheeler"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["state_a_data"] == [{"month": 6, "count": 700}]
    assert data["state_b_data"] == [{"month": 6, "count": 700}]
