"""Live features Phase A: /live-query/* answered from stored tables by default
(LIVE_SCRAPE_FALLBACK=False), never touching the government site, with scope
enforced on all three axes (state, RTO, category).

Sibling-row seeds throughout: every clamp has a neighbour whose rows would
visibly change the number if the clamp leaked --
  state:    DL1 (Delhi) next to Maharashtra
  RTO:      MH2 next to MH1 (MH1 = 100+50, MH2 = 900 -> state = 1050)
  category: HONDA two-wheeler rows next to HONDA four-wheeler rows
"""
import pytest

from app.core.auth import get_current_user
from app.main import app
from app.models.models import (
    RTO, MakerCategoryTotal, MakerFuelTotal, Registration, State, User, UserScope, VehicleCategoryScope,
)
from app.services import stored_live_service

HONDA = "HONDA CARS INDIA LTD"
TATA = "TATA MOTORS LTD"
HERO = "HERO MOTOCORP LTD"

MH_STATE = dict(scope_type=UserScope.STATE, scope_state_code="MH", scope_state_name="Maharashtra")
MH1_RTO = dict(
    scope_type=UserScope.RTO, scope_state_code="MH", scope_state_name="Maharashtra",
    scope_rto_code="MH1", scope_rto_name="MH1",
)
FOUR_WHEELER = dict(scope_type=UserScope.NATIONAL, scope_vehicle_category=VehicleCategoryScope.FOUR_WHEELER)


def _login_as(**scope):
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, email="s@example.com", role="viewer", is_active=True, **scope
    )


@pytest.fixture(autouse=True)
def _no_live_site(monkeypatch):
    """Any call into the live scraping service fails the test loudly."""
    async def _boom(*a, **k):
        raise AssertionError("stored path must not touch the live site")
    for name in ("get_or_scrape_maker_query", "get_top_makers_leaderboard", "search_makers", "get_site_rto_codes"):
        monkeypatch.setattr(f"app.api.v1.endpoints.live_query.{name}", _boom)
    stored_live_service.reset_maker_list()
    yield
    stored_live_service.reset_maker_list()
    app.dependency_overrides.pop(get_current_user, None)


def _reg(rto, state, month, maker, count, state_name=None):
    return Registration(
        state_code=state, state_name=state_name or {"MH": "Maharashtra", "DL": "Delhi"}[state],
        rto_code=rto, rto_name=rto, vehicle_class="All", vehicle_category="Other",
        year=2025, month=month, maker=maker, count=count, is_supplementary=False,
    )


def _mct(rto, state, maker, vclass, cat, count):
    return MakerCategoryTotal(
        state_code=state, state_name={"MH": "Maharashtra", "DL": "Delhi"}[state], rto_code=rto, rto_name=rto,
        year=2025, maker=maker, vehicle_class=vclass, vehicle_category=cat, count=count,
    )


def _mft(rto, state, maker, fuel, count):
    return MakerFuelTotal(
        state_code=state, state_name={"MH": "Maharashtra", "DL": "Delhi"}[state], rto_code=rto, rto_name=rto,
        year=2025, maker=maker, fuel_type=fuel, count=count,
    )


async def _seed(db):
    await db.merge(State(state_code="MH", state_name="Maharashtra"))
    await db.merge(State(state_code="DL", state_name="Delhi"))
    for code, st in (("MH1", "MH"), ("MH2", "MH"), ("DL1", "DL")):
        await db.merge(RTO(rto_code=code, rto_name=code, state_code=st))
    await db.commit()  # parents first: no relationship() orders the INSERTs
    db.add_all([
        _reg("MH1", "MH", 1, HONDA, 100), _reg("MH1", "MH", 2, HONDA, 50),
        _reg("MH2", "MH", 1, HONDA, 900),
        _reg("DL1", "DL", 1, HONDA, 7),
        _reg("MH1", "MH", 3, TATA, 4), _reg("MH1", "MH", 3, HERO, 6),
        # A supplementary (class-pass) row must never be added in.
        Registration(state_code="MH", state_name="Maharashtra", rto_code="MH1", rto_name="MH1",
                     vehicle_class="MOTOR CAR", vehicle_category="Four-Wheeler", year=2025, month=1,
                     maker=None, count=5000, is_supplementary=True),
        _mct("MH1", "MH", HONDA, "MOTOR CAR", "Four-Wheeler", 30),
        _mct("MH1", "MH", HONDA, "M-CYCLE/SCOOTER", "Two-Wheeler", 70),
        _mct("MH2", "MH", HONDA, "MOTOR CAR", "Four-Wheeler", 300),
        _mct("MH1", "MH", TATA, "MOTOR CAR", "Four-Wheeler", 40),
        _mct("MH1", "MH", HERO, "M-CYCLE/SCOOTER", "Two-Wheeler", 500),
        _mct("DL1", "DL", TATA, "MOTOR CAR", "Four-Wheeler", 9999),
        _mft("MH1", "MH", HONDA, "PETROL", 90),
        _mft("MH2", "MH", HONDA, "PETROL", 700),
        _mft("MH1", "MH", TATA, "DIESEL", 40),
        _mft("MH1", "MH", HERO, "PETROL", 400),
        _mft("DL1", "DL", HERO, "PETROL", 99999),
    ])
    await db.commit()


async def _get(client, path, **params):
    r = await client.get(f"/api/v1/live-query/{path}", params=params)
    assert r.status_code == 200, r.text
    return r.json()


# ---- /maker -----------------------------------------------------------------

async def test_maker_lookup_without_fuel_is_monthly_from_registrations(client, db_session):
    await _seed(db_session)
    body = await _get(client, "maker", state_code="MH", year=2025, maker=HONDA.lower())
    assert body["source"] == "stored"
    assert body["as_of"] and len(body["as_of"]) == 10  # YYYY-MM-DD
    assert body["grain"] == "month"
    # Same shape as the live response, monthly: MH1+MH2 in Jan, MH1 in Feb.
    assert body["records"] == [
        {"month": 1, "category": "ALL", "count": 1000},
        {"month": 2, "category": "ALL", "count": 50},
    ]
    assert {"state_code", "year", "maker", "fuel", "rto", "records"} <= body.keys()


async def test_maker_lookup_rto_scope_excludes_sibling_rto(client, db_session):
    await _seed(db_session)
    _login_as(**MH1_RTO)
    body = await _get(client, "maker", state_code="MH", year=2025, maker=HONDA)  # no rto passed
    assert body["rto"] == "MH1"
    assert sum(r["count"] for r in body["records"]) == 150  # not 1050


async def test_maker_lookup_state_scope_cannot_read_other_state(client, db_session):
    await _seed(db_session)
    _login_as(**MH_STATE)
    r = await client.get("/api/v1/live-query/maker", params={"state_code": "DL", "year": 2025, "maker": HONDA})
    assert r.status_code == 403


async def test_maker_lookup_with_fuel_is_yearly_from_maker_fuel_totals(client, db_session):
    await _seed(db_session)
    body = await _get(client, "maker", state_code="MH", year=2025, maker=HONDA, fuel="petrol")
    assert body["grain"] == "year"
    assert body["records"] == [{"month": 0, "category": "PETROL", "count": 790}]
    body = await _get(client, "maker", state_code="MH", year=2025, maker=HONDA, fuel="PETROL", rto="MH1")
    assert body["records"] == [{"month": 0, "category": "PETROL", "count": 90}]


async def test_maker_lookup_category_scope_uses_category_rows_only(client, db_session):
    await _seed(db_session)
    _login_as(**FOUR_WHEELER)
    body = await _get(client, "maker", state_code="MH", year=2025, maker=HONDA)
    # Four-wheeler only (MH1 30 + MH2 300); the 70 two-wheeler rows and the
    # all-category registrations total (1050) must not leak.
    assert body["records"] == [{"month": 0, "category": "MOTOR CAR", "count": 330}]
    assert body["grain"] == "year"


async def test_fuel_plus_category_is_refused_not_estimated(client, db_session):
    await _seed(db_session)
    _login_as(**FOUR_WHEELER)
    body = await _get(client, "maker", state_code="MH", year=2025, maker=HONDA, fuel="PETROL")
    assert body["records"] == []
    assert "not held" in body["unanswerable_reason"]


# ---- /leaderboard -----------------------------------------------------------

async def test_leaderboard_by_fuel_from_maker_fuel_totals(client, db_session):
    await _seed(db_session)
    body = await _get(client, "leaderboard", state_code="MH", year=2025, fuel="PETROL")
    assert body["source"] == "stored"
    assert body["makers"] == [{"maker": HONDA, "total": 790}, {"maker": HERO, "total": 400}]


async def test_leaderboard_without_fuel_from_maker_category_totals(client, db_session):
    await _seed(db_session)
    body = await _get(client, "leaderboard", state_code="MH", year=2025)
    assert body["makers"] == [
        {"maker": HERO, "total": 500}, {"maker": HONDA, "total": 400}, {"maker": TATA, "total": 40},
    ]


async def test_leaderboard_rto_scope_excludes_sibling(client, db_session):
    await _seed(db_session)
    _login_as(**MH1_RTO)
    body = await _get(client, "leaderboard", state_code="MH", year=2025, fuel="PETROL")
    assert body["makers"] == [{"maker": HERO, "total": 400}, {"maker": HONDA, "total": 90}]


async def test_leaderboard_category_scope(client, db_session):
    await _seed(db_session)
    _login_as(**FOUR_WHEELER)
    body = await _get(client, "leaderboard", state_code="MH", year=2025)
    assert body["makers"] == [{"maker": HONDA, "total": 330}, {"maker": TATA, "total": 40}]
    refused = await _get(client, "leaderboard", state_code="MH", year=2025, fuel="PETROL")
    assert refused["makers"] == [] and refused["unanswerable_reason"]


async def test_leaderboard_state_scope_forbidden_elsewhere(client, db_session):
    await _seed(db_session)
    _login_as(**MH_STATE)
    r = await client.get("/api/v1/live-query/leaderboard", params={"state_code": "DL", "year": 2025})
    assert r.status_code == 403


# ---- /makers/search and /rtos ----------------------------------------------

async def test_maker_search_uses_our_vocabulary(client, db_session):
    await _seed(db_session)
    names = await _get(client, "makers/search", q="hon")
    assert names == [HONDA]
    names = await _get(client, "makers/search", q="ltd")
    assert names == [HERO, HONDA, TATA]  # substring, alphabetical (no prefix hit)
    names = await _get(client, "makers/search", q="ta")
    assert names == [TATA]  # prefix hit


async def test_maker_search_category_scope_filters_makers(client, db_session):
    await _seed(db_session)
    _login_as(**FOUR_WHEELER)
    names = await _get(client, "makers/search", q="ltd")
    assert names == [HONDA, TATA]  # HERO is two-wheeler only


async def test_maker_search_geo_scope_lists_only_makers_in_scope(client, db_session):
    """N7: a state/RTO account's search lists only makers with rows in its
    own state/RTO. TATA sells in MH1 and DL1; HERO only in MH1; HONDA in MH1+MH2."""
    await _seed(db_session)
    db_session.add(_mct("DL1", "DL", "DELHI ONLY MOTORS LTD", "MOTOR CAR", "Four-Wheeler", 5))
    db_session.add(_mct("MH2", "MH", "PUNE ONLY LTD", "MOTOR CAR", "Four-Wheeler", 5))
    await db_session.commit()
    stored_live_service.reset_maker_list()
    assert await _get(client, "makers/search", q="ltd") == [
        "DELHI ONLY MOTORS LTD", HERO, HONDA, "PUNE ONLY LTD", TATA]  # national: everything
    _login_as(**MH_STATE)
    assert await _get(client, "makers/search", q="ltd") == [HERO, HONDA, "PUNE ONLY LTD", TATA]
    _login_as(**MH1_RTO)
    assert await _get(client, "makers/search", q="ltd") == [HERO, HONDA, TATA]  # MH2-only maker hidden


async def test_maker_search_scope_set_is_cached_per_scope_key(client, db_session, monkeypatch):
    """N5: the per-category allowed set was recomputed (~1s on prod) on every
    search. Now one query per scope key per TTL; distinct keys never share."""
    await _seed(db_session)
    calls = []
    real_execute = db_session.execute

    async def counting_execute(stmt, *a, **k):
        if "maker_category_totals" in str(stmt) and "DISTINCT" in str(stmt).upper() and "RECURSIVE" not in str(stmt).upper():
            calls.append(str(stmt))
        return await real_execute(stmt, *a, **k)
    monkeypatch.setattr(db_session, "execute", counting_execute)
    _login_as(**FOUR_WHEELER)
    for q in ("ltd", "hon", "ta", "ltd"):
        await _get(client, "makers/search", q=q)
    assert len(calls) == 1, f"allowed-maker set must be cached, ran {len(calls)}x"
    assert await _get(client, "makers/search", q="ltd") == [HONDA, TATA]
    # A different scope (2W) is a different key: its own query and its own answer.
    _login_as(scope_type=UserScope.NATIONAL, scope_vehicle_category=VehicleCategoryScope.TWO_WHEELER)
    assert await _get(client, "makers/search", q="ltd") == [HERO, HONDA]
    assert len(calls) == 2
    stored_live_service.reset_maker_list()  # post-scrape hook clears it
    await _get(client, "makers/search", q="ltd")
    assert len(calls) == 3


async def test_rtos_lists_stored_rtos_clamped_to_rto_user(client, db_session):
    await _seed(db_session)
    assert await _get(client, "rtos", state_code="MH") == ["MH1", "MH2"]
    _login_as(**MH1_RTO)
    assert await _get(client, "rtos", state_code="MH") == ["MH1"]


async def test_live_fallback_flag_routes_to_live_and_labels_it(client, db_session, monkeypatch):
    await _seed(db_session)
    calls = []

    async def fake_live(db, state_code, year, maker, fuel=None, rto=None):
        calls.append((state_code, maker))
        return [{"month": 3, "category": "LMV", "count": 4}]
    monkeypatch.setattr("app.api.v1.endpoints.live_query.get_or_scrape_maker_query", fake_live)
    monkeypatch.setattr("app.api.v1.endpoints.live_query.settings.LIVE_SCRAPE_FALLBACK", True)
    body = await _get(client, "maker", state_code="MH", year=2025, maker=HONDA)
    assert calls and body["source"] == "live" and body["records"][0]["count"] == 4


def test_server_timeouts_are_below_browser_timeouts():
    from app.api.v1.endpoints import live_query
    assert live_query.LIVE_MAKER_SERVER_TIMEOUT_S < 30  # vahan.ts getLiveMakerQuery timeout
    assert live_query.LEADERBOARD_SERVER_TIMEOUT_S < 60  # vahan.ts getLiveMakerLeaderboard timeout
