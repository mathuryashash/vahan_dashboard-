"""Tests for the geographic access hierarchy (app.core.scope): a state- or
RTO-scoped user must never see another state's/RTO's data, regardless of
what they pass in the query string or URL."""
from app.core.auth import get_current_user
from app.main import app
from app.models.models import MakerCategoryTotal, RTO, Registration, State, User, UserScope
from app.services import live_scrape_service

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
    # merge (not add) -- with no relationship() between these models, a
    # plain add()+commit doesn't order INSERTs by FK dependency, so the
    # Registration rows below can be sent before their still-pending
    # State/RTO rows. merge() writes immediately, so it self-orders.
    await db_session.merge(State(state_code="DL", state_name="Delhi"))
    await db_session.merge(State(state_code="MH", state_name="Maharashtra"))
    await db_session.merge(RTO(rto_code="DL1", rto_name="Delhi RTO", state_code="DL"))
    await db_session.merge(RTO(rto_code="MH1", rto_name="Test RTO MH1", state_code="MH"))
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


async def _seed_sibling_rto(db_session):
    """A SECOND RTO inside Maharashtra, so "clamped to MH1" is distinguishable
    from "clamped to Maharashtra". With only one RTO per state (which is all
    _seed_two_states gives) an RTO-tier user's numbers are identical either
    way, and a test written on that seed passes against the leak it is
    supposed to catch. MH1 = 100, MH2 = 900, so Maharashtra = 1000: any
    whole-state answer is visibly 10x the RTO's own."""
    await _seed_two_states(db_session)
    await db_session.merge(RTO(rto_code="MH2", rto_name="Sibling RTO MH2", state_code="MH"))
    db_session.add(
        Registration(
            state_code="MH", state_name="Maharashtra", rto_code="MH2", rto_name="Sibling RTO MH2",
            vehicle_class="All", vehicle_category="Other", year=2026, month=1,
            maker="HONDA", count=900, is_supplementary=False,
        )
    )
    await db_session.commit()


async def test_leaderboard_ranking_is_clamped_to_the_users_own_rto(db_session, monkeypatch):
    """The fourth recurrence of this bug shape, found by review.

    /live-query/leaderboard was guarded by require_state_code alone, which
    an RTO-tier account passes trivially -- its RTO is in that state -- so
    it ranked the whole STATE's top makers, which is the state tier's
    product. Exercised at the service layer because the endpoint
    live-scrapes each ranked maker; the scrape is stubbed so this stays
    offline and tests only the narrowing.
    """
    await db_session.merge(State(state_code="MH", state_name="Maharashtra"))
    await db_session.merge(RTO(rto_code="MH1", rto_name="Test RTO MH1", state_code="MH"))
    await db_session.merge(RTO(rto_code="MH2", rto_name="Sibling RTO MH2", state_code="MH"))
    await db_session.commit()
    geo = dict(state_code="MH", state_name="Maharashtra", year=2026,
               vehicle_class="M-CYCLE/SCOOTER", vehicle_category="Two-Wheeler")
    db_session.add_all([
        MakerCategoryTotal(**geo, rto_code="MH1", rto_name="Test RTO MH1", maker="ALPHA", count=100),
        # Bigger, so an unclamped ranking puts it first and the leak is
        # unmistakable rather than a subtle ordering difference.
        MakerCategoryTotal(**geo, rto_code="MH2", rto_name="Sibling RTO MH2", maker="BETA", count=900),
    ])
    await db_session.commit()

    async def _fake_scrape(db, state_code, year, maker, fuel=None, rto=None):
        return [{"month": 1, "category": "TWO WHEELER(NT)", "count": 5}]

    monkeypatch.setattr(live_scrape_service, "get_or_scrape_maker_query", _fake_scrape)

    own = await live_scrape_service.get_top_makers_leaderboard(db_session, "MH", 2026, rto="MH1")
    assert [m["maker"] for m in own] == ["ALPHA"], "RTO-scoped leaderboard leaked a sibling RTO's maker"

    # A state-tier caller (rto=None) must still see both -- the clamp has to
    # narrow the RTO tier without shrinking the tier above it.
    whole_state = await live_scrape_service.get_top_makers_leaderboard(db_session, "MH", 2026)
    assert {m["maker"] for m in whole_state} == {"ALPHA", "BETA"}


async def test_rto_scoped_user_kpis_exclude_sibling_rto(client, db_session):
    """The live-proven leak: get_effective_state clamped an RTO-tier account
    only to its STATE, so /summary/kpis returned a figure identical to the
    state-tier account's (~18.6x the RTO's real volume in production)."""
    await _seed_sibling_rto(db_session)
    _login_as(**MH_RTO)
    try:
        # No rto param exists on this endpoint at all -- so this IS the
        # omission case, and it must narrow to MH1 rather than widen to MH.
        response = await client.get("/api/v1/summary/kpis", params={"year": 2026})
        assert response.status_code == 200
        assert response.json()["total_this_month"] == 100, "expected MH1 only, not all of Maharashtra (1000)"

        # Naming their own state explicitly must not widen it back either.
        widened = await client.get(
            "/api/v1/summary/kpis", params={"year": 2026, "state": "Maharashtra"}
        )
        assert widened.json()["total_this_month"] == 100
    finally:
        app.dependency_overrides[get_current_user] = lambda: User(id=0, role="admin", is_active=True, scope_type=UserScope.NATIONAL)


async def test_state_scoped_user_still_sees_whole_state(client, db_session):
    """The other side of the clamp: a STATE-tier account must keep seeing
    every RTO in its state, so the fix narrows the RTO tier without
    accidentally narrowing the tier above it."""
    await _seed_sibling_rto(db_session)
    _login_as(scope_type=UserScope.STATE, scope_state_code="MH", scope_state_name="Maharashtra")
    try:
        response = await client.get("/api/v1/summary/kpis", params={"year": 2026})
        assert response.json()["total_this_month"] == 1000
    finally:
        app.dependency_overrides[get_current_user] = lambda: User(id=0, role="admin", is_active=True, scope_type=UserScope.NATIONAL)


async def test_rto_scoped_user_top_makers_exclude_sibling_rto(client, db_session):
    """/categories/top-makers reported HERO MOTOCORP at ~36.6x the RTO's real
    number in production -- whole-state maker volume under an RTO login."""
    await _seed_sibling_rto(db_session)
    _login_as(**MH_RTO)
    try:
        response = await client.get("/api/v1/categories/top-makers", params={"year": 2026})
        assert response.status_code == 200
        assert response.json() == [{"maker": "HONDA", "count": 100}]
    finally:
        app.dependency_overrides[get_current_user] = lambda: User(id=0, role="admin", is_active=True, scope_type=UserScope.NATIONAL)


async def test_rto_scoped_user_gets_only_own_rto_raw_rows(client, db_session):
    """/registrations/ returned byte-identical raw rows for the state-tier and
    RTO-tier accounts in production."""
    await _seed_sibling_rto(db_session)
    _login_as(**MH_RTO)
    try:
        response = await client.get("/api/v1/registrations/", params={"year": 2026})
        assert response.status_code == 200
        rows = response.json()
        assert [r["count"] for r in rows] == [100], "sibling RTO MH2's rows must not be returned"
    finally:
        app.dependency_overrides[get_current_user] = lambda: User(id=0, role="admin", is_active=True, scope_type=UserScope.NATIONAL)


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
    await _seed_two_states(db_session)
    _login_as(**MH_RTO)
    try:
        blocked = await client.get("/api/v1/rto/DL1/analysis", params={"year": 2025})
        assert blocked.status_code == 403

        allowed = await client.get("/api/v1/rto/MH1/analysis", params={"year": 2025})
        assert allowed.status_code == 200
    finally:
        app.dependency_overrides[get_current_user] = lambda: User(id=0, role="admin", is_active=True, scope_type=UserScope.NATIONAL)


async def test_rto_scoped_user_cannot_widen_live_query_by_omitting_rto(client, db_session, monkeypatch):
    """Omitting `rto` must mean "my own RTO", never "the whole state". The
    guard originally only rejected a DIFFERENT rto, so leaving the parameter
    off entirely skipped the clamp and returned whole-state data (caught in
    code review) -- the same bypass get_effective_state prevents on the
    state axis."""
    seen = {}

    async def _capture(db, state_code, year, maker, fuel=None, rto=None):
        seen["rto"] = rto
        return []

    monkeypatch.setattr("app.api.v1.endpoints.live_query.get_or_scrape_maker_query", _capture)

    await _seed_two_states(db_session)
    _login_as(**MH_RTO)
    try:
        # No `rto` given at all -- must be narrowed to the user's own MH1.
        response = await client.get(
            "/api/v1/live-query/maker",
            params={"state_code": "MH", "year": 2026, "maker": "HONDA"},
        )
        assert response.status_code == 200
        assert seen["rto"] == "MH1", (
            f"expected the clamp to narrow to the user's own RTO, got {seen['rto']!r} "
            "-- omitting the parameter must not widen scope to the whole state"
        )

        # Naming someone else's RTO stays a hard refusal.
        blocked = await client.get(
            "/api/v1/live-query/maker",
            params={"state_code": "MH", "year": 2026, "maker": "HONDA", "rto": "DL1"},
        )
        assert blocked.status_code == 403
    finally:
        app.dependency_overrides[get_current_user] = lambda: User(id=0, role="admin", is_active=True, scope_type=UserScope.NATIONAL)


async def test_national_user_is_unrestricted(client, db_session):
    await _seed_two_states(db_session)
    response = await client.get("/api/v1/summary/kpis", params={"year": 2026, "state": "Maharashtra"})
    assert response.status_code == 200
    assert response.json()["total_this_month"] == 100


async def test_rto_scoped_user_rto_list_excludes_sibling_rto(client, db_session):
    """GET /rto/{state}/list must return ONLY the caller's own RTO.

    Regression: this route was guarded by require_state_code alone, which an
    RTO-tier account passes trivially -- its RTO lives in that state -- while
    the query itself had no RTO filter. It therefore returned every RTO in
    the state ranked by volume, which is the state tier's product. Found by
    live audit: a UP32 account received all 76 UP RTOs.

    _seed_sibling_rto is what makes this test meaningful: with one RTO per
    state, "clamped to MH1" and "clamped to Maharashtra" return the same
    rows and the test would pass against the leak.
    """
    await _seed_sibling_rto(db_session)
    _login_as(**MH_RTO)
    # fy_filter(2025) covers Apr-2025..Mar-2026, which includes the Jan-2026
    # seed rows.
    response = await client.get("/api/v1/rto/MH/list", params={"year": 2025})
    assert response.status_code == 200
    codes = [row["rto_code"] for row in response.json()]
    assert codes == ["MH1"], (
        f"RTO-scoped user saw {codes} -- the sibling RTO's volume (and its "
        "rank against the caller's own) must never be returned"
    )


async def test_state_scoped_user_rto_list_still_sees_every_rto_in_state(client, db_session):
    """The fix above must not narrow the STATE tier, which is sold exactly
    this per-RTO league table for its own state."""
    await _seed_sibling_rto(db_session)
    _login_as(scope_type=UserScope.STATE, scope_state_code="MH", scope_state_name="Maharashtra")
    response = await client.get("/api/v1/rto/MH/list", params={"year": 2025})
    assert response.status_code == 200
    assert sorted(row["rto_code"] for row in response.json()) == ["MH1", "MH2"]
