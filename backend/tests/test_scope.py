"""Tests for the geographic access hierarchy (app.core.scope): a state- or
RTO-scoped user must never see another state's/RTO's data, regardless of
what they pass in the query string or URL."""
from app.core.auth import get_current_user
from app.main import app
from app.models.models import RTO, Registration, State, User, UserScope

DELHI = dict(scope_type=UserScope.STATE, scope_state_code="DL", scope_state_name="Delhi")
MH_RTO = dict(
    scope_type=UserScope.RTO, scope_state_code="MH", scope_state_name="Maharashtra",
    scope_rto_code="MH1", scope_rto_name="Test RTO MH1",
)


def _login_as(**scope_kwargs):
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, email="scoped@example.com", role="viewer", is_active=True, **scope_kwargs
    )


async def _seed_two_states(db_session):
    db_session.add_all([
        Registration(
            state_code="DL", state_name="Delhi", rto_code="DL1", rto_name="Delhi RTO",
            vehicle_class="All", vehicle_category="Other", year=2026, month=1,
            maker="HONDA", count=10, is_supplementary=False,
        ),
        Registration(
            state_code="MH", state_name="Maharashtra", rto_code="MH1", rto_name="Test RTO MH1",
            vehicle_class="All", vehicle_category="Other", year=2026, month=1,
            maker="HONDA", count=100, is_supplementary=False,
        ),
    ])
    await db_session.commit()


async def test_state_scoped_user_cannot_see_another_states_kpis(client, db_session):
    await _seed_two_states(db_session)
    _login_as(**DELHI)
    try:
        # Explicitly asks for Maharashtra's data -- must be silently clamped
        # back to Delhi's, not honored.
        response = await client.get("/api/v1/summary/kpis", params={"year": 2026, "state": "Maharashtra"})
        assert response.status_code == 200
        assert response.json()["total_this_month"] == 10  # Delhi's count, not MH's 100
    finally:
        app.dependency_overrides[get_current_user] = lambda: User(id=0, role="admin", is_active=True, scope_type=UserScope.NATIONAL)


async def test_rto_scoped_user_blocked_from_another_rto_analysis(client, db_session):
    db_session.add_all([
        State(state_code="DL", state_name="Delhi"),
        State(state_code="MH", state_name="Maharashtra"),
        RTO(rto_code="DL1", rto_name="Delhi RTO", state_code="DL"),
        RTO(rto_code="MH1", rto_name="Test RTO MH1", state_code="MH"),
    ])
    await _seed_two_states(db_session)
    _login_as(**MH_RTO)
    try:
        blocked = await client.get("/api/v1/rto/DL1/analysis", params={"year": 2025})
        assert blocked.status_code == 403

        allowed = await client.get("/api/v1/rto/MH1/analysis", params={"year": 2025})
        assert allowed.status_code == 200
    finally:
        app.dependency_overrides[get_current_user] = lambda: User(id=0, role="admin", is_active=True, scope_type=UserScope.NATIONAL)


async def test_national_user_is_unrestricted(client, db_session):
    await _seed_two_states(db_session)
    response = await client.get("/api/v1/summary/kpis", params={"year": 2026, "state": "Maharashtra"})
    assert response.status_code == 200
    assert response.json()["total_this_month"] == 100
