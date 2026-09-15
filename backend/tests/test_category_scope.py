"""Tests for the vehicle-category access boundary (User.scope_vehicle_category,
enforced in app.core.scope): a category-scoped account must never see another
segment's data -- not by asking for it, not by omitting the filter, and not
via an endpoint that never had a vehicle_category param to clamp.

The seed below is deliberately the real row shape, not a convenient one: the
canonical maker-pass rows (is_supplementary=False) carry vehicle_class='All'
and no real category, and the only rows that DO carry a category are the
vehicle_class-dimension pass (is_supplementary=True). A test seeded with
"maker + real category on one row" would pass against code that never works
in production -- see apply_total_filters' docstring.
"""
from app.core.auth import get_current_user
from app.core.query_filters import classify_live_category
from app.main import app
from app.models.models import (
    RTO, FuelCategoryTotal, MakerCategoryTotal, MakerFuelTotal, OEMMonthlySales, Registration,
    State, User, UserRole, UserScope, VehicleCategoryScope,
)

FOUR_WHEELER = dict(scope_type=UserScope.NATIONAL, scope_vehicle_category=VehicleCategoryScope.FOUR_WHEELER)
TWO_WHEELER = dict(scope_type=UserScope.NATIONAL, scope_vehicle_category=VehicleCategoryScope.TWO_WHEELER)

CAR_COUNT = 40
BIKE_COUNT = 400


def _login_as(**scope_kwargs):
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, email="segment@example.com", role=UserRole.ANALYST, is_active=True, **scope_kwargs
    )


def _restore_national_admin():
    app.dependency_overrides[get_current_user] = lambda: User(
        id=0, email="test-admin@example.com", role=UserRole.ADMIN, is_active=True,
        scope_type=UserScope.NATIONAL, scope_vehicle_category=None,
    )


async def _seed(db_session):
    # merge (not add) for the parent rows -- same FK-ordering reason as
    # test_scope.py's _seed_two_states.
    await db_session.merge(State(state_code="DL", state_name="Delhi"))
    await db_session.merge(RTO(rto_code="DL1", rto_name="Delhi RTO", state_code="DL"))
    # Committed before the children: merge() alone leaves these pending, and
    # the crosstab tables' own rto_code FK is checked in whatever order the
    # unit of work happens to emit the INSERTs in.
    await db_session.commit()
    geo = dict(state_code="DL", state_name="Delhi", rto_code="DL1", rto_name="Delhi RTO")
    db_session.add_all([
        # vehicle_class-dimension pass: carries a real category, no maker.
        Registration(**geo, vehicle_class="MOTOR CAR", vehicle_category="Four-Wheeler",
                     year=2026, month=1, count=CAR_COUNT, is_supplementary=True),
        Registration(**geo, vehicle_class="M-CYCLE/SCOOTER", vehicle_category="Two-Wheeler",
                     year=2026, month=1, count=BIKE_COUNT, is_supplementary=True),
        # canonical maker-pass: carries a maker, no real category.
        Registration(**geo, vehicle_class="All", vehicle_category="Other", maker="MARUTI SUZUKI",
                     year=2026, month=1, count=CAR_COUNT, is_supplementary=False),
        Registration(**geo, vehicle_class="All", vehicle_category="Other", maker="HERO MOTOCORP",
                     year=2026, month=1, count=BIKE_COUNT, is_supplementary=False),
        MakerCategoryTotal(**geo, year=2026, maker="MARUTI SUZUKI", vehicle_class="MOTOR CAR",
                           vehicle_category="Four-Wheeler", count=CAR_COUNT),
        MakerCategoryTotal(**geo, year=2026, maker="HERO MOTOCORP", vehicle_class="M-CYCLE/SCOOTER",
                           vehicle_category="Two-Wheeler", count=BIKE_COUNT),
        FuelCategoryTotal(**geo, year=2026, fuel_type="PETROL", vehicle_class="MOTOR CAR",
                          vehicle_category="Four-Wheeler", count=CAR_COUNT),
        FuelCategoryTotal(**geo, year=2026, fuel_type="PETROL", vehicle_class="M-CYCLE/SCOOTER",
                          vehicle_category="Two-Wheeler", count=BIKE_COUNT),
        MakerFuelTotal(**geo, year=2026, maker="MARUTI SUZUKI", fuel_type="PETROL", count=CAR_COUNT),
        MakerFuelTotal(**geo, year=2026, maker="HERO MOTOCORP", fuel_type="PETROL", count=BIKE_COUNT),
        OEMMonthlySales(source="FADA", year=2026, month=6, category="PV", maker="MARUTI SUZUKI",
                        count=CAR_COUNT, source_document="June 2026 release"),
        OEMMonthlySales(source="FADA", year=2026, month=6, category="Two-Wheeler", maker="HERO MOTOCORP",
                        count=BIKE_COUNT, source_document="June 2026 release"),
    ])
    await db_session.commit()


# --- the two negative cases the whole feature exists for -------------------

async def test_scoped_user_cannot_widen_by_passing_another_category(client, db_session):
    await _seed(db_session)
    _login_as(**FOUR_WHEELER)
    try:
        response = await client.get(
            "/api/v1/summary/kpis", params={"year": 2026, "vehicle_category": "Two-Wheeler"}
        )
        assert response.status_code == 200
        assert response.json()["total_this_month"] == CAR_COUNT
    finally:
        _restore_national_admin()


async def test_scoped_user_cannot_widen_by_omitting_the_category(client, db_session):
    """Omitting the filter must mean "my category", never "all categories" --
    the easiest possible bypass if this were a UI-side filter."""
    await _seed(db_session)
    _login_as(**FOUR_WHEELER)
    try:
        response = await client.get("/api/v1/summary/kpis", params={"year": 2026})
        assert response.status_code == 200
        assert response.json()["total_this_month"] == CAR_COUNT
    finally:
        _restore_national_admin()


async def test_two_wheeler_and_four_wheeler_accounts_see_different_totals(client, db_session):
    """Same request, two accounts, two answers -- and neither is the market
    total (which is what an unscoped account gets, see the last test here)."""
    await _seed(db_session)
    for scope, expected in ((FOUR_WHEELER, CAR_COUNT), (TWO_WHEELER, BIKE_COUNT)):
        _login_as(**scope)
        try:
            response = await client.get("/api/v1/summary/trend", params={"year": 2026})
            assert response.status_code == 200
            assert [row["count"] for row in response.json()] == [expected]
        finally:
            _restore_national_admin()


# --- endpoints with no vehicle_category param to clamp --------------------

async def test_category_breakdown_returns_only_the_scoped_category(client, db_session):
    """/categories/ groups BY category and never had a filter param -- it
    also drives the category dropdown on Makers/Comparison, so clamping it
    is what locks those selectors."""
    await _seed(db_session)
    _login_as(**FOUR_WHEELER)
    try:
        response = await client.get("/api/v1/categories/", params={"year": 2026})
        assert response.status_code == 200
        assert [row["vehicle_category"] for row in response.json()] == ["Four-Wheeler"]
    finally:
        _restore_national_admin()


async def test_top_makers_excludes_other_categories_makers(client, db_session):
    await _seed(db_session)
    _login_as(**FOUR_WHEELER)
    try:
        response = await client.get("/api/v1/categories/top-makers", params={"year": 2026})
        assert response.status_code == 200
        assert [row["maker"] for row in response.json()] == ["MARUTI SUZUKI"]
    finally:
        _restore_national_admin()


async def test_maker_fuel_breakdown_excludes_other_categories_makers(client, db_session):
    """MakerFuelTotal has no category column at all -- the makers have to be
    restricted via MakerCategoryTotal or a 4W account sees 2W manufacturers."""
    await _seed(db_session)
    _login_as(**FOUR_WHEELER)
    try:
        response = await client.get(
            "/api/v1/categories/maker-fuel-breakdown", params={"year": 2026, "fuel_group": "ICE"}
        )
        assert response.status_code == 200
        assert [row["maker"] for row in response.json()] == ["MARUTI SUZUKI"]
    finally:
        _restore_national_admin()


async def test_rto_analysis_maker_list_excludes_other_categories_makers(client, db_session):
    """Per-RTO maker breakdown must come from the category-aware crosstab:
    the maker-pass rows it used to read carry vehicle_category='Other' for
    every row, so they can only say WHICH makers exist, never how much of a
    maker's volume belongs to this account's category."""
    await _seed(db_session)
    _login_as(**FOUR_WHEELER)
    try:
        # FY 2025 = April 2025 - March 2026, which is where the month=1/2026
        # seed rows land.
        response = await client.get("/api/v1/rto/DL1/analysis", params={"year": 2025})
        assert response.status_code == 200
        assert [row["maker"] for row in response.json()["makers"]] == ["MARUTI SUZUKI"]
    finally:
        _restore_national_admin()


async def test_rto_analysis_count_excludes_a_makers_other_category_volume(client, db_session):
    """The leak the maker allowlist alone does NOT close: a maker selling in
    several categories (Mahindra ships both cars and commercial vehicles)
    passes the allowlist legitimately, but its count must still be only this
    account's category. Asserting the number, not just the maker list --
    without this, summing the category-blind maker-pass rows would report
    CAR_COUNT + truck_count here and the test would still pass on names."""
    truck_count = 7
    await _seed(db_session)
    geo = dict(state_code="DL", state_name="Delhi", rto_code="DL1", rto_name="Delhi RTO")
    db_session.add_all([
        # Same maker, same RTO, both categories -- and a maker-pass row that
        # carries their COMBINED volume, exactly as the real scraper writes it.
        MakerCategoryTotal(**geo, year=2026, maker="MAHINDRA", vehicle_class="MOTOR CAR",
                           vehicle_category="Four-Wheeler", count=CAR_COUNT),
        MakerCategoryTotal(**geo, year=2026, maker="MAHINDRA", vehicle_class="GOODS CARRIER",
                           vehicle_category="Commercial Vehicle", count=truck_count),
        Registration(**geo, vehicle_class="All", vehicle_category="Other", maker="MAHINDRA",
                     year=2026, month=1, count=CAR_COUNT + truck_count, is_supplementary=False),
    ])
    await db_session.commit()

    _login_as(**FOUR_WHEELER)
    try:
        response = await client.get("/api/v1/rto/DL1/analysis", params={"year": 2025})
        assert response.status_code == 200
        rows = {row["maker"]: row["count"] for row in response.json()["makers"]}
        assert "MAHINDRA" in rows, "a multi-category maker must still appear for its own category"
        assert rows["MAHINDRA"] == CAR_COUNT, (
            f"expected only the Four-Wheeler volume ({CAR_COUNT}), got {rows['MAHINDRA']} "
            f"-- the Commercial Vehicle volume ({truck_count}) leaked in"
        )
    finally:
        _restore_national_admin()


async def test_state_ranking_and_all_states_comparison_are_clamped(client, db_session):
    await _seed(db_session)
    _login_as(**TWO_WHEELER)
    try:
        ranking = await client.get("/api/v1/summary/state-ranking", params={"year": 2026})
        assert ranking.status_code == 200
        assert [row["total_count"] for row in ranking.json()] == [BIKE_COUNT]

        comparison = await client.get("/api/v1/comparison/all-states", params={"year": 2026})
        assert comparison.status_code == 200
        assert [row["count"] for row in comparison.json()] == [BIKE_COUNT]
    finally:
        _restore_national_admin()


async def test_yoy_monthly_is_clamped(client, db_session):
    await _seed(db_session)
    _login_as(**FOUR_WHEELER)
    try:
        response = await client.get("/api/v1/yoy/monthly", params={"year_a": 2025, "year_b": 2026})
        assert response.status_code == 200
        assert [row["year_2026"] for row in response.json()["data"]] == [CAR_COUNT]
    finally:
        _restore_national_admin()


async def test_raw_registration_rows_cannot_reach_another_category(client, db_session):
    """The rawest endpoint there is: ask for a two-wheeler vehicle_class
    directly and get nothing, not the row."""
    await _seed(db_session)
    _login_as(**FOUR_WHEELER)
    try:
        blocked = await client.get(
            "/api/v1/registrations/", params={"year": 2026, "vehicle_class": "M-CYCLE/SCOOTER"}
        )
        assert blocked.status_code == 200
        assert blocked.json() == []

        allowed = await client.get("/api/v1/registrations/", params={"year": 2026})
        assert {row["vehicle_class"] for row in allowed.json()} == {"MOTOR CAR"}
    finally:
        _restore_national_admin()


async def test_fada_industry_sales_are_clamped(client, db_session):
    """FADA labels its categories differently ("PV", not "Four-Wheeler") --
    the bridge must hold in both directions: only PV listed, Two-Wheeler
    refused outright."""
    await _seed(db_session)
    _login_as(**FOUR_WHEELER)
    try:
        categories = await client.get("/api/v1/oem-sales/categories", params={"year": 2026})
        assert categories.status_code == 200
        assert categories.json() == ["PV"]

        blocked = await client.get(
            "/api/v1/oem-sales/monthly", params={"category": "Two-Wheeler", "year": 2026}
        )
        assert blocked.status_code == 403

        blocked_trend = await client.get(
            "/api/v1/oem-sales/trend", params={"maker": "HERO MOTOCORP", "category": "Two-Wheeler"}
        )
        assert blocked_trend.status_code == 403
    finally:
        _restore_national_admin()


# --- the other half of an access boundary: it must not over-restrict ------

async def test_unscoped_user_still_sees_every_category(client, db_session):
    """The client fixture's stub admin has no category scope -- totals and
    maker lists must be exactly what they were before this feature."""
    await _seed(db_session)
    kpis = await client.get("/api/v1/summary/kpis", params={"year": 2026})
    assert kpis.json()["total_this_month"] == CAR_COUNT + BIKE_COUNT

    categories = await client.get("/api/v1/categories/", params={"year": 2026})
    assert {row["vehicle_category"] for row in categories.json()} == {"Four-Wheeler", "Two-Wheeler"}

    makers = await client.get("/api/v1/categories/top-makers", params={"year": 2026})
    assert {row["maker"] for row in makers.json()} == {"MARUTI SUZUKI", "HERO MOTOCORP"}

    # Paired with the two maker-restriction tests above: without them these
    # same two endpoints list both manufacturers, so those tests are proving
    # the restriction, not just an empty fixture.
    maker_fuel = await client.get(
        "/api/v1/categories/maker-fuel-breakdown", params={"year": 2026, "fuel_group": "ICE"}
    )
    assert {row["maker"] for row in maker_fuel.json()} == {"MARUTI SUZUKI", "HERO MOTOCORP"}

    rto = await client.get("/api/v1/rto/DL1/analysis", params={"year": 2025})
    assert {row["maker"] for row in rto.json()["makers"]} == {"MARUTI SUZUKI", "HERO MOTOCORP"}


async def test_scoped_user_can_still_narrow_within_their_own_category(client, db_session):
    """Clamping is a ceiling, not a lock: passing their own category (what
    the frontend does) must behave exactly like omitting it."""
    await _seed(db_session)
    _login_as(**TWO_WHEELER)
    try:
        response = await client.get(
            "/api/v1/summary/kpis", params={"year": 2026, "vehicle_category": "Two-Wheeler"}
        )
        assert response.json()["total_this_month"] == BIKE_COUNT
    finally:
        _restore_national_admin()


# --- admin API + the live-site taxonomy bridge ----------------------------

async def test_admin_can_create_a_category_scoped_user_and_typos_are_rejected(client, db_session):
    created = await client.post("/api/v1/users/", json={
        "email": "oem@example.com", "password": "s3cret-pw", "role": UserRole.ANALYST,
        "scope_vehicle_category": "Four-Wheeler",
    })
    assert created.status_code == 200
    assert created.json()["scope_vehicle_category"] == "Four-Wheeler"

    # A typo would match no row in any table, silently showing the account
    # nothing at all rather than the segment it was sold.
    rejected = await client.post("/api/v1/users/", json={
        "email": "typo@example.com", "password": "s3cret-pw", "scope_vehicle_category": "4W",
    })
    assert rejected.status_code == 400


def test_classify_live_category_maps_the_live_sites_own_taxonomy():
    """The analytics site reports a third vocabulary of its own; these are
    real labels captured from it (see tests/fixtures/
    analytics_monthwise_category_sample.html)."""
    assert classify_live_category("TWO WHEELER(NT)") == "Two-Wheeler"
    assert classify_live_category("THREE WHEELER(T)") == "Three-Wheeler"
    assert classify_live_category("FOUR WHEELER (Invalid Carriage)") == "Four-Wheeler"
    assert classify_live_category("LIGHT MOTOR VEHICLE") == "Four-Wheeler"
    assert classify_live_category("HEAVY PASSENGER VEHICLE") == "Commercial Vehicle"
    assert classify_live_category("MEDIUM GOODS VEHICLE") == "Commercial Vehicle"
    # Unmatched is never guessed into a real category.
    assert classify_live_category("OTHER THAN MENTIONED ABOVE") == "Other"
