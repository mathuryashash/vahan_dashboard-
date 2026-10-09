"""Round 4 / B + D: Category x Powertrain answered from the crosstab tables
instead of being refused.

/comparison/category-fuel  -- per state, calendar year, from fuel_category_totals
/categories/category-fuel-month -- one month, from state_month_category_fuel_totals,
                                   only when that table agrees with the crosstab
"""
from app.core.auth import get_current_user
from app.main import app
from app.models.models import (
    RTO, FuelCategoryTotal, MakerCategoryTotal, State, StateMonthCategoryFuelTotal, User, UserScope,
    VehicleCategoryScope,
)

STATES = {"MH": "Maharashtra", "DL": "Delhi"}


def _login_as(**scope):
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, email="s@example.com", role="viewer", is_active=True, **scope
    )


def _fct(rto, st, fuel, cls, cat, count, year=2025):
    return FuelCategoryTotal(state_code=st, state_name=STATES[st], rto_code=rto, rto_name=rto, year=year,
                             fuel_type=fuel, vehicle_class=cls, vehicle_category=cat, count=count)


def _mct(rto, st, cat, count, year=2025, maker="X"):
    return MakerCategoryTotal(state_code=st, state_name=STATES[st], rto_code=rto, rto_name=rto, year=year,
                              maker=maker, vehicle_class=cat, vehicle_category=cat, count=count)


def _smcft(st, month, cat, fuel, count, year=2025):
    return StateMonthCategoryFuelTotal(state_code=st, state_name=STATES[st], year=year, month=month,
                                       category=cat, fuel=fuel, count=count)


async def _seed(db):
    for code, name in STATES.items():
        await db.merge(State(state_code=code, state_name=name))
    for code, st in (("MH1", "MH"), ("MH2", "MH"), ("DL1", "DL")):
        await db.merge(RTO(rto_code=code, rto_name=code, state_code=st))
    await db.commit()
    db.add_all([
        # Maharashtra 4W: ICE = 100 + 20 (CNG) + 30 (MH2) ; EV = 10 ; 2W ICE 500
        _fct("MH1", "MH", "PETROL", "MOTOR CAR", "Four-Wheeler", 100),
        _fct("MH1", "MH", "PETROL/CNG", "MOTOR CAR", "Four-Wheeler", 20),
        _fct("MH2", "MH", "DIESEL", "MOTOR CAR", "Four-Wheeler", 30),
        _fct("MH1", "MH", "PURE EV", "MOTOR CAR", "Four-Wheeler", 10),
        _fct("MH1", "MH", "PETROL", "M-CYCLE/SCOOTER", "Two-Wheeler", 500),
        _fct("DL1", "DL", "PETROL", "MOTOR CAR", "Four-Wheeler", 50),
        # category totals that the crosstab reconciles against (exactly).
        _mct("MH1", "MH", "Four-Wheeler", 130), _mct("MH2", "MH", "Four-Wheeler", 30),
        _mct("MH1", "MH", "Two-Wheeler", 500), _mct("DL1", "DL", "Four-Wheeler", 50),
    ])
    await db.commit()


async def _get(client, path, **params):
    r = await client.get(f"/api/v1/{path}", params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def test_category_fuel_comparison_per_state(client, db_session):
    await _seed(db_session)
    body = await _get(client, "comparison/category-fuel", year=2025, vehicle_category="Four-Wheeler", fuel_group="ICE")
    assert body["available"] and body["source"] == "fuel_category_totals" and body["grain"] == "year"
    assert [(s["state_name"], s["count"]) for s in body["states"]] == [("Maharashtra", 150), ("Delhi", 50)]
    assert body["total"] == 200 and body["coverage_pct_off"] == 0.0 and not body["coverage_incomplete"]
    ev = await _get(client, "comparison/category-fuel", year=2025, vehicle_category="Four-Wheeler", fuel_group="EV")
    assert [(s["state_name"], s["count"]) for s in ev["states"]] == [("Maharashtra", 10)]


async def test_category_fuel_comparison_missing_year_is_a_reason_not_a_zero(client, db_session):
    await _seed(db_session)
    body = await _get(client, "comparison/category-fuel", year=2019, vehicle_category="Four-Wheeler", fuel_group="ICE")
    assert body["available"] is False and body["unanswerable_reason"] and body["states"] == []


async def test_category_fuel_comparison_flags_incomplete_year(client, db_session):
    await _seed(db_session)
    db_session.add(_mct("MH1", "MH", "Four-Wheeler", 1000, maker="Y"))  # category totals far above the crosstab
    await db_session.commit()
    body = await _get(client, "comparison/category-fuel", year=2025, vehicle_category="Four-Wheeler", fuel_group="ICE")
    assert body["coverage_incomplete"] is True
    mh = next(s for s in body["states"] if s["state_name"] == "Maharashtra")
    assert mh["incomplete"] is True and mh["count"] == 150
    dl = next(s for s in body["states"] if s["state_name"] == "Delhi")
    assert dl["incomplete"] is False


async def test_category_fuel_comparison_scope(client, db_session):
    await _seed(db_session)
    try:
        _login_as(scope_type=UserScope.STATE, scope_state_code="MH", scope_state_name="Maharashtra")
        body = await _get(client, "comparison/category-fuel", year=2025, vehicle_category="Four-Wheeler",
                          fuel_group="ICE")
        assert [s["state_name"] for s in body["states"]] == ["Maharashtra"]
        _login_as(scope_type=UserScope.RTO, scope_state_code="MH", scope_state_name="Maharashtra",
                  scope_rto_code="MH1", scope_rto_name="MH1")
        body = await _get(client, "comparison/category-fuel", year=2025, vehicle_category="Four-Wheeler",
                          fuel_group="ICE")
        assert body["states"][0]["count"] == 120  # MH2's 30 diesel excluded
        _login_as(scope_type=UserScope.NATIONAL, scope_vehicle_category=VehicleCategoryScope.TWO_WHEELER)
        body = await _get(client, "comparison/category-fuel", year=2025, vehicle_category="Four-Wheeler",
                          fuel_group="ICE")
        assert body["vehicle_category"] == "Two-Wheeler"
        assert [(s["state_name"], s["count"]) for s in body["states"]] == [("Maharashtra", 500)]
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def test_category_fuel_comparison_rejects_bad_group(client, db_session):
    r = await client.get("/api/v1/comparison/category-fuel",
                         params={"year": 2025, "vehicle_category": "Four-Wheeler", "fuel_group": "Petrol"})
    assert r.status_code == 422


# ---- month-level ------------------------------------------------------------

async def _seed_month(db, portal_jan_ev=4, portal_feb_ev=6):
    await _seed(db)
    db.add_all([
        _smcft("MH", 1, "FOUR WHEELER (NT)", "PURE EV", portal_jan_ev),
        _smcft("MH", 2, "FOUR WHEELER (NT)", "PURE EV", portal_feb_ev),
        _smcft("MH", 1, "FOUR WHEELER (NT)", "PETROL", 60),
        _smcft("MH", 2, "LIGHT MOTOR VEHICLE", "PETROL", 90),
        _smcft("MH", 1, "TWO WHEELER(NT)", "PURE EV", 999),
    ])
    await db.commit()


async def test_month_figure_served_when_year_totals_agree(client, db_session):
    await _seed_month(db_session)  # portal EV 4+6 = 10 == crosstab 10
    body = await _get(client, "categories/category-fuel-month", year=2025, month=1,
                      vehicle_category="Four-Wheeler", fuel_group="EV", state="Maharashtra")
    assert body["available"] is True and body["count"] == 4
    assert body["source"] == "state_month_category_fuel_totals"


async def test_month_figure_refused_when_year_totals_disagree(client, db_session):
    await _seed_month(db_session)  # portal ICE 60+90 = 150 == crosstab 150 -> served
    ok = await _get(client, "categories/category-fuel-month", year=2025, month=2,
                    vehicle_category="Four-Wheeler", fuel_group="ICE", state="Maharashtra")
    assert ok["available"] and ok["count"] == 90
    TTLCacheReset = __import__("app.core.cache", fromlist=["TTLCache"]).TTLCache
    TTLCacheReset.clear_all()
    db_session.add(_smcft("MH", 3, "FOUR WHEELER (NT)", "PURE EV", 50))  # portal EV now 60 vs 10
    await db_session.commit()
    body = await _get(client, "categories/category-fuel-month", year=2025, month=1,
                      vehicle_category="Four-Wheeler", fuel_group="EV", state="Maharashtra")
    assert body["available"] is False and body["count"] is None and body["unanswerable_reason"]


async def test_month_figure_missing_month(client, db_session):
    await _seed_month(db_session)
    body = await _get(client, "categories/category-fuel-month", year=2025, month=7,
                      vehicle_category="Four-Wheeler", fuel_group="EV", state="Maharashtra")
    assert body["available"] is False and "07/2025" in body["unanswerable_reason"]


async def test_month_figure_refused_for_rto_scope(client, db_session):
    await _seed_month(db_session)
    try:
        _login_as(scope_type=UserScope.RTO, scope_state_code="MH", scope_state_name="Maharashtra",
                  scope_rto_code="MH1", scope_rto_name="MH1")
        body = await _get(client, "categories/category-fuel-month", year=2025, month=1,
                          vehicle_category="Four-Wheeler", fuel_group="EV")
        assert body["available"] is False and body["count"] is None
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def test_category_fuel_coverage_is_measured_within_the_category(client, db_session):
    """Round 5 P3: coverage_pct_off compared ALL-category fct against ALL-
    category mct, so a 4W user's ratio was a whole-state figure. A 2W gap
    must not move the 4W coverage."""
    await _seed(db_session)
    db_session.add(_mct("MH1", "MH", "Two-Wheeler", 900, maker="Y"))  # 2W category total far above the 2W crosstab
    await db_session.commit()
    body = await _get(client, "comparison/category-fuel", year=2025, vehicle_category="Four-Wheeler", fuel_group="ICE")
    mh = next(s for s in body["states"] if s["state_name"] == "Maharashtra")
    assert mh["coverage_pct_off"] == 0.0 and mh["incomplete"] is False
    assert body["coverage_pct_off"] == 0.0 and body["coverage_incomplete"] is False
