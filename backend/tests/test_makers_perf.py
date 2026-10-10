"""Round 7: the Makers page's coverage-gap check reads a precomputed summary
(maker_rto_coverage) instead of scanning six years of maker_category_totals
per request, and /maker-fuel-breakdown sums in SQL instead of in Python.

Both are pure speed changes, so every test here pins EQUALITY: the summary
path must return exactly what the live query returns, every endpoint must
return the same body with and without the summary, and every scope axis must
still clamp. Seeds carry a SIBLING on every axis (a second RTO in the same
state, a second state, a second category) so "clamped" and "not clamped"
produce different numbers.
"""
import pytest
from sqlalchemy import text

from app.core.auth import get_current_user
from app.core.cache import TTLCache
from app.core.query_filters import makers_with_coverage_gaps
from app.main import app
from app.models.models import MakerCategoryTotal, MakerFuelTotal, RTO, State, User, UserScope
from app.services import maker_coverage
from app.services.maker_coverage import (
    NATIONAL, live_coverage, refresh_maker_rto_coverage, stored_coverage,
)

MAKERS = ["HERO", "TATA", "SMALL EV", "GONE"]

MH_STATE = dict(scope_type=UserScope.STATE, scope_state_code="MH", scope_state_name="Maharashtra")
MH1_RTO = dict(scope_type=UserScope.RTO, scope_state_code="MH", scope_state_name="Maharashtra",
               scope_rto_code="MH1", scope_rto_name="MH1")
TWO_W = dict(scope_type=UserScope.NATIONAL, scope_vehicle_category="Two-Wheeler")
FOUR_W = dict(scope_type=UserScope.NATIONAL, scope_vehicle_category="Four-Wheeler")


def _login_as(**scope):
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, email="scoped@example.com", role="viewer", is_active=True, **scope)


def _reset_login():
    app.dependency_overrides[get_current_user] = lambda: User(
        id=0, role="admin", is_active=True, scope_type=UserScope.NATIONAL)


def _mct(state, rto, year, maker, cls, cat, count):
    code = rto[:2]
    return MakerCategoryTotal(state_code=code, state_name=state, rto_code=rto, rto_name=rto, year=year,
                              maker=maker, vehicle_class=cls, vehicle_category=cat, count=count)


def _mft(state, rto, year, maker, fuel, count):
    return MakerFuelTotal(state_code=rto[:2], state_name=state, rto_code=rto, rto_name=rto, year=year,
                          maker=maker, fuel_type=fuel, count=count)


async def _seed(db):
    """MH has MH1 + sibling MH2; DL has DL1..DL6 so a maker can collapse.

    GONE reaches 6 Delhi RTOs in 2023 and 1 in 2025 -> a coverage gap
    nationally and in Delhi, but not for an RTO account (always empty).
    """
    await db.merge(State(state_code="MH", state_name="Maharashtra"))
    await db.merge(State(state_code="DL", state_name="Delhi"))
    for r in ["MH1", "MH2"] + [f"DL{i}" for i in range(1, 7)]:
        await db.merge(RTO(rto_code=r, rto_name=r, state_code=r[:2]))
    await db.commit()
    rows = []
    for year in (2023, 2024, 2025):
        rows += [
            _mct("Maharashtra", "MH1", year, "HERO", "M-CYCLE/SCOOTER", "Two-Wheeler", 100 + year % 10),
            _mct("Maharashtra", "MH2", year, "HERO", "M-CYCLE/SCOOTER", "Two-Wheeler", 1000 + year % 10),
            _mct("Maharashtra", "MH1", year, "TATA", "MOTOR CAR", "Four-Wheeler", 50),
            _mct("Maharashtra", "MH2", year, "TATA", "MOTOR CAR", "Four-Wheeler", 70),
            # Same maker, second category: TATA also has a few two-wheelers.
            _mct("Maharashtra", "MH2", year, "TATA", "M-CYCLE/SCOOTER", "Two-Wheeler", 3),
            _mct("Delhi", "DL1", year, "HERO", "M-CYCLE/SCOOTER", "Two-Wheeler", 400),
            _mct("Delhi", "DL1", year, "SMALL EV", "E-RICKSHAW(P)", "Three-Wheeler", 9),
        ]
    rows += [_mct("Delhi", f"DL{i}", 2023, "GONE", "MOTOR CAR", "Four-Wheeler", 20) for i in range(1, 7)]
    rows += [_mct("Delhi", "DL1", 2025, "GONE", "MOTOR CAR", "Four-Wheeler", 20)]
    rows += [
        _mft("Maharashtra", "MH1", 2025, "HERO", "PETROL", 90), _mft("Maharashtra", "MH2", 2025, "HERO", "PETROL", 900),
        _mft("Maharashtra", "MH1", 2025, "HERO", "ELECTRIC(BOV)", 7), _mft("Maharashtra", "MH2", 2025, "HERO", "ELECTRIC(BOV)", 11),
        _mft("Delhi", "DL1", 2025, "HERO", "ELECTRIC(BOV)", 5), _mft("Delhi", "DL2", 2025, "HERO", "PURE EV", 1),
        _mft("Delhi", "DL1", 2025, "SMALL EV", "ELECTRIC(BOV)", 24), _mft("Delhi", "DL1", 2025, "ZETA EV", "ELECTRIC(BOV)", 24),
        _mft("Maharashtra", "MH1", 2025, "TATA", "DIESEL", 60), _mft("Maharashtra", "MH1", 2025, "TATA", "PETROL/HYBRID", 4),
    ]
    db.add_all(rows)
    await db.commit()


@pytest.mark.parametrize("state", [None, "Maharashtra", "Delhi"])
async def test_summary_rows_equal_the_live_query(db_session, state):
    await _seed(db_session)
    assert await refresh_maker_rto_coverage(db_session.bind)
    for floor in (2017, 2019, 2022, 2024):
        stored = await stored_coverage(db_session, MAKERS, floor, state)
        live = await live_coverage(db_session, MakerCategoryTotal, MAKERS, floor, state)
        assert stored is not None
        assert sorted(stored) == sorted(live), (state, floor)
    # Values, not just shape: HERO is in MH1+MH2+DL1 nationally, 2 in MH.
    national = {(m, y): n for m, y, n in await stored_coverage(db_session, ["HERO"], 2022, None)}
    assert national == {("HERO", 2023): 3, ("HERO", 2024): 3, ("HERO", 2025): 3}
    mh = {(m, y): n for m, y, n in await stored_coverage(db_session, ["HERO"], 2022, "Maharashtra")}
    assert mh == {("HERO", 2023): 2, ("HERO", 2024): 2, ("HERO", 2025): 2}


async def test_gap_flags_identical_with_and_without_summary(db_session):
    await _seed(db_session)
    cases = [(None, None), ("Delhi", None), ("Maharashtra", None), ("Maharashtra", "MH1")]
    before = [await makers_with_coverage_gaps(db_session, MakerCategoryTotal, 2025, MAKERS, state=s, rto_code=r)
              for s, r in cases]
    assert before[0] == {"GONE"} and before[1] == {"GONE"} and before[3] == set()
    assert await refresh_maker_rto_coverage(db_session.bind)
    after = [await makers_with_coverage_gaps(db_session, MakerCategoryTotal, 2025, MAKERS, state=s, rto_code=r)
             for s, r in cases]
    assert after == before


async def test_a_write_after_the_build_falls_back_to_live_and_rebuilds(db_session):
    """A scrape that never calls the hook must not leave a stale answer:
    max(id) moves with every insert, so the reader sees the change at once."""
    await _seed(db_session)
    assert await refresh_maker_rto_coverage(db_session.bind)
    maker_coverage._last_auto_refresh = float("-inf")
    # GONE comes back to all six Delhi RTOs in 2025: no longer a gap.
    db_session.add_all([_mct("Delhi", f"DL{i}", 2025, "GONE", "MOTOR CAR", "Four-Wheeler", 20) for i in range(2, 7)])
    await db_session.commit()

    assert await stored_coverage(db_session, MAKERS, 2019, None) is None, "stale summary was served"
    assert await makers_with_coverage_gaps(db_session, MakerCategoryTotal, 2025, MAKERS) == set()
    # The reader scheduled one background rebuild; once it lands the summary
    # is current again and agrees with the live query.
    assert maker_coverage.pending is not None
    await maker_coverage.pending
    stored = await stored_coverage(db_session, MAKERS, 2019, None)
    assert stored is not None
    assert sorted(stored) == sorted(await live_coverage(db_session, MakerCategoryTotal, MAKERS, 2019, None))


async def test_rebuild_is_a_no_op_when_nothing_changed_and_skips_when_locked(db_session):
    await _seed(db_session)
    assert await refresh_maker_rto_coverage(db_session.bind)
    first = (await db_session.execute(text(
        "SELECT refreshed_at FROM derived_table_state WHERE name = 'maker_rto_coverage'"))).scalar()
    await db_session.commit()
    assert await refresh_maker_rto_coverage(db_session.bind)
    again = (await db_session.execute(text(
        "SELECT refreshed_at FROM derived_table_state WHERE name = 'maker_rto_coverage'"))).scalar()
    await db_session.commit()
    assert again == first, "unchanged source must not rebuild"
    # Another rebuild holding the lock: this one steps aside.
    async with db_session.bind.connect() as other:
        await other.execute(text("SELECT pg_advisory_lock(:k)"), {"k": maker_coverage._LOCK_KEY})
        try:
            db_session.add(_mct("Delhi", "DL3", 2025, "HERO", "M-CYCLE/SCOOTER", "Two-Wheeler", 1))
            await db_session.commit()
            assert await refresh_maker_rto_coverage(db_session.bind) is False
        finally:
            await other.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": maker_coverage._LOCK_KEY})
    national_rows = (await db_session.execute(text(
        "SELECT count(*) FROM maker_rto_coverage WHERE state_name = :n"), {"n": NATIONAL})).scalar()
    assert national_rows > 0


# --- endpoint level: same body with and without the summary, every scope ---

ENDPOINTS = [
    "/api/v1/categories/maker-category-breakdown?year=2025&vehicle_category=Two-Wheeler&limit=20",
    "/api/v1/categories/maker-category-breakdown?year=2025&vehicle_category=Four-Wheeler&limit=20",
    "/api/v1/categories/maker-category-breakdown?year=2025&limit=20",
    "/api/v1/categories/top-makers?year=2025&vehicle_category=Four-Wheeler&limit=20",
    "/api/v1/categories/maker-category-breakdown?year=2025&state=Delhi&limit=20",
    "/api/v1/categories/maker-fuel-breakdown?year=2025&fuel_group=EV&limit=20",
    "/api/v1/categories/maker-fuel-breakdown?year=2025&maker=HERO",
]
SCOPES = [None, MH_STATE, MH1_RTO, TWO_W, FOUR_W]


async def _bodies(client):
    out = {}
    for scope in SCOPES:
        _login_as(**scope) if scope else _reset_login()
        for url in ENDPOINTS:
            TTLCache.clear_all()
            r = await client.get(url)
            assert r.status_code == 200, (scope, url, r.text)
            out[(str(scope), url)] = r.json()
    _reset_login()
    return out


async def test_endpoints_identical_with_and_without_summary(client, db_session):
    await _seed(db_session)
    try:
        live = await _bodies(client)
        assert await refresh_maker_rto_coverage(db_session.bind)
        assert await _bodies(client) == live
    finally:
        _reset_login()


async def test_endpoint_values_and_scope_clamps(client, db_session):
    await _seed(db_session)
    assert await refresh_maker_rto_coverage(db_session.bind)
    url_4w = "/api/v1/categories/maker-category-breakdown?year=2025&vehicle_category=Four-Wheeler&limit=20"
    try:
        # National: TATA 4W is MH1 50 + MH2 70; GONE collapsed -> partial.
        _reset_login()
        assert (await client.get(url_4w)).json() == [
            {"maker": "TATA", "count": 120, "partial": False},
            {"maker": "GONE", "count": 20, "partial": True},
        ]
        # RTO MH1: only MH1's 50, never the sibling MH2's 70; no gap check.
        _login_as(**MH1_RTO)
        TTLCache.clear_all()
        assert (await client.get(url_4w + "&state=Delhi")).json() == [
            {"maker": "TATA", "count": 50, "partial": False}]
        # State MH asking for Delhi is clamped to MH (both RTOs).
        _login_as(**MH_STATE)
        TTLCache.clear_all()
        assert (await client.get(url_4w + "&state=Delhi")).json() == [
            {"maker": "TATA", "count": 120, "partial": False}]
        # Two-Wheeler account asking for Four-Wheeler gets ONLY two-wheelers:
        # HERO 105+1005+400, TATA's 3 two-wheelers -- never TATA's 120 cars.
        _login_as(**TWO_W)
        TTLCache.clear_all()
        assert (await client.get(url_4w)).json() == [
            {"maker": "HERO", "count": 1510, "partial": False},
            {"maker": "TATA", "count": 3, "partial": False},
        ]
        # Category accounts get no Maker x Fuel answer at all (no category axis).
        TTLCache.clear_all()
        assert (await client.get("/api/v1/categories/maker-fuel-breakdown?year=2025&fuel_group=EV")).json() == []
    finally:
        _reset_login()


async def test_maker_fuel_breakdown_sums_in_sql_with_scope_and_stable_ties(client, db_session):
    await _seed(db_session)
    try:
        _reset_login()
        body = (await client.get("/api/v1/categories/maker-fuel-breakdown?year=2025&fuel_group=EV&limit=20")).json()
        # HERO EV = 7 + 11 + 5 + 1 (PURE EV counts as EV) = 24, tying SMALL EV
        # and ZETA EV at 24: ties come out by name, every time.
        assert body == [{"maker": "HERO", "count": 24}, {"maker": "SMALL EV", "count": 24},
                        {"maker": "ZETA EV", "count": 24}]
        TTLCache.clear_all()
        split = (await client.get("/api/v1/categories/maker-fuel-breakdown?year=2025&maker=TATA")).json()
        assert split == [{"fuel_group": "ICE", "count": 60}, {"fuel_group": "Hybrid", "count": 4}]
        _login_as(**MH1_RTO)
        TTLCache.clear_all()
        assert (await client.get("/api/v1/categories/maker-fuel-breakdown?year=2025&fuel_group=EV")).json() == [
            {"maker": "HERO", "count": 7}]
        _login_as(**MH_STATE)
        TTLCache.clear_all()
        assert (await client.get("/api/v1/categories/maker-fuel-breakdown?year=2025&fuel_group=EV&state=Delhi")).json() == [
            {"maker": "HERO", "count": 18}]
    finally:
        _reset_login()
