"""Scope tests for GET /api/v1/categories/crosstab-coverage.

This endpoint answers "which years does each crosstab have ANY data for".
The frontend uses it to tell 'this year was never scraped' apart from
'scraped, and this maker genuinely sold zero' -- so an answer computed
outside the caller's scope gives them the wrong answer to BOTH questions,
and discloses that data exists in a state / category they did not buy.

It already clamped the RTO axis (see scoped_rto) but clamped neither the
STATE nor the VEHICLE-CATEGORY axis, which is exactly the recurring shape in
this codebase: the axis that HAS a dependency reads as proof the route is
protected, and the axes that don't are invisible.

Each test seeds a SIBLING -- a second state, a second category -- so that
"clamped to the caller" is distinguishable from "not clamped at all". With a
single state in the fixture both produce the same year list and the test
would pass against the very leak it exists to catch.
"""
from app.core.auth import get_current_user
from app.main import app
from app.models.models import (
    FuelCategoryTotal, MakerCategoryTotal, MakerFuelTotal, RTO, State, User, UserScope,
)

DELHI = dict(scope_type=UserScope.STATE, scope_state_code="DL", scope_state_name="Delhi")
MH_RTO = dict(
    scope_type=UserScope.RTO, scope_state_code="MH", scope_state_name="Maharashtra",
    scope_rto_code="MH1", scope_rto_name="Test RTO MH1",
)
NATIONAL_4W = dict(scope_type=UserScope.NATIONAL, scope_vehicle_category="Four-Wheeler")


def _login_as(**scope_kwargs):
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, email="scoped@example.com", role="viewer", is_active=True, **scope_kwargs
    )


def _reset_login():
    app.dependency_overrides[get_current_user] = lambda: User(
        id=0, role="admin", is_active=True, scope_type=UserScope.NATIONAL
    )


async def _seed_two_states_crosstabs(db_session):
    """Delhi has crosstab data for 2024 only; Maharashtra for 2025 only.

    Disjoint years on purpose: a leak is then a year that APPEARS rather than
    a count that is wrong, so it cannot be missed by an assertion on labels.
    """
    await db_session.merge(State(state_code="DL", state_name="Delhi"))
    await db_session.merge(State(state_code="MH", state_name="Maharashtra"))
    await db_session.merge(RTO(rto_code="DL1", rto_name="Delhi RTO", state_code="DL"))
    await db_session.merge(RTO(rto_code="MH1", rto_name="Test RTO MH1", state_code="MH"))
    await db_session.commit()
    db_session.add_all([
        MakerCategoryTotal(
            state_code="DL", state_name="Delhi", rto_code="DL1", rto_name="Delhi RTO",
            year=2024, vehicle_class="MOTOR CAR", vehicle_category="Four-Wheeler",
            maker="TATA", count=10,
        ),
        MakerCategoryTotal(
            state_code="MH", state_name="Maharashtra", rto_code="MH1", rto_name="Test RTO MH1",
            year=2025, vehicle_class="MOTOR CAR", vehicle_category="Four-Wheeler",
            maker="TATA", count=100,
        ),
        FuelCategoryTotal(
            state_code="DL", state_name="Delhi", rto_code="DL1", rto_name="Delhi RTO",
            year=2024, vehicle_class="MOTOR CAR", vehicle_category="Four-Wheeler",
            fuel_type="PETROL", count=10,
        ),
        FuelCategoryTotal(
            state_code="MH", state_name="Maharashtra", rto_code="MH1", rto_name="Test RTO MH1",
            year=2025, vehicle_class="MOTOR CAR", vehicle_category="Four-Wheeler",
            fuel_type="PETROL", count=100,
        ),
        MakerFuelTotal(
            state_code="DL", state_name="Delhi", rto_code="DL1", rto_name="Delhi RTO",
            year=2024, maker="TATA", fuel_type="PETROL", count=10,
        ),
        MakerFuelTotal(
            state_code="MH", state_name="Maharashtra", rto_code="MH1", rto_name="Test RTO MH1",
            year=2025, maker="TATA", fuel_type="PETROL", count=100,
        ),
    ])
    await db_session.commit()


async def test_state_scoped_user_crosstab_coverage_excludes_other_states_years(client, db_session):
    """A Delhi account must not learn that 2025 exists in Maharashtra.

    Live shape of the leak: the route declared scoped_rto (so it READ as
    scoped) but the query had no state predicate, so every state-tier account
    received the national year list for all three crosstabs.
    """
    await _seed_two_states_crosstabs(db_session)
    _login_as(**DELHI)
    try:
        response = await client.get("/api/v1/categories/crosstab-coverage")
        assert response.status_code == 200
        body = response.json()
        for crosstab in ("maker_category", "fuel_category", "maker_fuel"):
            assert body[crosstab] == [2024], (
                f"{crosstab} returned {body[crosstab]} to a Delhi account -- "
                "2025 exists only in Maharashtra and must not be disclosed"
            )
    finally:
        _reset_login()


async def test_rto_scoped_user_crosstab_coverage_excludes_other_states_years(client, db_session):
    """The RTO tier is clamped on BOTH axes, not just the one it had.

    scoped_rto alone already excluded Delhi's rows here (rto_code differs),
    so this asserts the state clamp does not break the tier that was working.
    """
    await _seed_two_states_crosstabs(db_session)
    _login_as(**MH_RTO)
    try:
        body = (await client.get("/api/v1/categories/crosstab-coverage")).json()
        assert body["maker_category"] == [2025]
        assert body["fuel_category"] == [2025]
        assert body["maker_fuel"] == [2025]
    finally:
        _reset_login()


async def test_national_user_crosstab_coverage_is_unrestricted(client, db_session):
    """The inverse test: a clamp that over-applies is a silent product
    regression nobody files as a bug. A national account must still see every
    year from every state."""
    await _seed_two_states_crosstabs(db_session)
    response = await client.get("/api/v1/categories/crosstab-coverage")
    assert response.status_code == 200
    body = response.json()
    assert body["maker_category"] == [2025, 2024]
    assert body["fuel_category"] == [2025, 2024]
    assert body["maker_fuel"] == [2025, 2024]


async def test_category_scoped_user_crosstab_coverage_excludes_other_categories(client, db_session):
    """A Four-Wheeler account must not learn a year exists on the strength of
    Two-Wheeler rows alone.

    Seeds a SIBLING CATEGORY: 2024 is Four-Wheeler, 2026 is Two-Wheeler only.
    Unclamped, both years come back and the account is told 2026 was scraped
    for it -- so an empty 2026 chart reads as 'scraped, real zero' when the
    truth is 'this account has no 2026 data at all'.

    maker_fuel is deliberately NOT category-clamped and is asserted to still
    carry both years: MakerFuelTotal has no vehicle_category column, so any
    category predicate on it would be a fabrication (the 947x membership-filter
    bug). Coverage is an existence signal, not a volume, so the honest answer
    is the unclamped year list -- /maker-fuel-breakdown already returns []
    outright for these accounts.
    """
    await _seed_two_states_crosstabs(db_session)
    db_session.add_all([
        MakerCategoryTotal(
            state_code="DL", state_name="Delhi", rto_code="DL1", rto_name="Delhi RTO",
            year=2026, vehicle_class="M-CYCLE/SCOOTER", vehicle_category="Two-Wheeler",
            maker="HERO", count=50,
        ),
        FuelCategoryTotal(
            state_code="DL", state_name="Delhi", rto_code="DL1", rto_name="Delhi RTO",
            year=2026, vehicle_class="M-CYCLE/SCOOTER", vehicle_category="Two-Wheeler",
            fuel_type="PETROL", count=50,
        ),
        MakerFuelTotal(
            state_code="DL", state_name="Delhi", rto_code="DL1", rto_name="Delhi RTO",
            year=2026, maker="HERO", fuel_type="PETROL", count=50,
        ),
    ])
    await db_session.commit()

    _login_as(**NATIONAL_4W)
    try:
        body = (await client.get("/api/v1/categories/crosstab-coverage")).json()
        assert body["maker_category"] == [2025, 2024], (
            f"maker_category returned {body['maker_category']} -- 2026 is "
            "Two-Wheeler-only and must not be offered to a Four-Wheeler account"
        )
        assert body["fuel_category"] == [2025, 2024], (
            f"fuel_category returned {body['fuel_category']} -- 2026 is Two-Wheeler-only"
        )
        assert body["maker_fuel"] == [2026, 2025, 2024], (
            "MakerFuelTotal has no category column; inventing a category "
            "predicate for it is the membership-filter bug, not a fix"
        )
    finally:
        _reset_login()


async def test_crosstab_coverage_cache_is_not_shared_across_scopes(client, db_session):
    """Cache-key regression.

    The key was (user_rto,). scoped_rto returns None for BOTH a national and a
    state-scoped account, so those two tiers collided on the single key None:
    whichever called first populated it and the other was served that answer.
    Adding the state/category filters WITHOUT extending the key would have
    converted this read leak into a nondeterministic cross-tenant cache leak,
    which is strictly worse.

    Ordered national-first on purpose -- that is the direction that hands the
    wider answer to the narrower account.
    """
    await _seed_two_states_crosstabs(db_session)
    national = (await client.get("/api/v1/categories/crosstab-coverage")).json()
    assert national["maker_category"] == [2025, 2024]

    _login_as(**DELHI)
    try:
        scoped = (await client.get("/api/v1/categories/crosstab-coverage")).json()
        assert scoped["maker_category"] == [2024], (
            f"state-scoped account was served {scoped['maker_category']} -- "
            "the national entry was served from a cache key that omits scope"
        )
    finally:
        _reset_login()
