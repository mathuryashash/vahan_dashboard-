"""/categories/brand-options -- the OEM/Brand picker's list.

Seeded to mirror the real 2026 cases the rule was measured against: BMW and
Piaggio-style makers whose two-wheeler SHARE is modest but whose volume is
real, a Mercedes-style maker with a handful of stray two-wheeler rows, the
two non-company rows VAHAN carries, and Hero Honda under its double-spaced
spelling.
"""
from app.core.auth import get_current_user
from app.main import app
from app.models.models import RTO, State, User, UserRole, UserScope, VehicleCategoryScope
from app.services.scraper_service import persist_maker_category_batch

URL = "/api/v1/categories/brand-options"
BIKE, CAR = "M-CYCLE/SCOOTER", "MOTOR CAR"


async def _seed(db_session):
    for code, name, rto in (("DL", "Delhi", "DL1"), ("MH", "Maharashtra", "MH1")):
        await db_session.merge(State(state_code=code, state_name=name))
        await db_session.merge(RTO(rto_code=rto, rto_name=f"{name} RTO", state_code=code))

    delhi = [
        {"maker": "BMW INDIA PVT LTD", "vehicle_class": BIKE, "count": 3000},
        {"maker": "BMW INDIA PVT LTD", "vehicle_class": CAR, "count": 12000},
        {"maker": "MERCEDES -BENZ AG", "vehicle_class": BIKE, "count": 50},
        {"maker": "MERCEDES -BENZ AG", "vehicle_class": CAR, "count": 1600},
        {"maker": "HONDA MOTORCYCLE AND SCOOTER INDIA (P) LTD", "vehicle_class": BIKE, "count": 5000},
        {"maker": "MARUTI SUZUKI INDIA LTD", "vehicle_class": CAR, "count": 8000},
        {"maker": "HERO HONDA MOTORS  LTD", "vehicle_class": BIKE, "count": 200},
        {"maker": "OTHERS", "vehicle_class": BIKE, "count": 9000},
        {"maker": "NIC TEST ACCOUNT-1", "vehicle_class": BIKE, "count": 500},
    ]
    # BMW barely present in Maharashtra: 5 bikes, far under the floor locally.
    mumbai = [{"maker": "BMW INDIA PVT LTD", "vehicle_class": BIKE, "count": 5}]

    await persist_maker_category_batch(
        db_session, {"state_name": "Delhi", "rto_code": "DL1", "rto_name": "Delhi RTO", "records": delhi},
        state_code="DL", year=2026)
    await persist_maker_category_batch(
        db_session, {"state_name": "Maharashtra", "rto_code": "MH1", "rto_name": "Maharashtra RTO", "records": mumbai},
        state_code="MH", year=2026)
    await db_session.commit()


async def _makers(client, **params):
    r = await client.get(URL, params={"year": 2026, **params})
    assert r.status_code == 200, r.text
    return r.json()


async def test_two_wheeler_list_is_decided_by_volume_not_share(client, db_session):
    """BMW is only ~20% two-wheeler but has 3,005 bikes -- a real maker.
    Mercedes has 50 stray bike rows -- noise. A share rule gets this backwards."""
    await _seed(db_session)
    names = [m["maker"] for m in await _makers(client, vehicle_category="Two-Wheeler")]

    assert "BMW INDIA PVT LTD" in names
    assert "MERCEDES -BENZ AG" not in names
    assert "MARUTI SUZUKI INDIA LTD" not in names, "a pure four-wheeler maker leaked into two-wheelers"
    assert names[0] == "HONDA MOTORCYCLE AND SCOOTER INDIA (P) LTD", "largest first"


async def test_four_wheeler_list_excludes_bike_makers(client, db_session):
    await _seed(db_session)
    names = [m["maker"] for m in await _makers(client, vehicle_category="Four-Wheeler")]

    assert {"BMW INDIA PVT LTD", "MERCEDES -BENZ AG", "MARUTI SUZUKI INDIA LTD"} <= set(names)
    assert "HONDA MOTORCYCLE AND SCOOTER INDIA (P) LTD" not in names


async def test_all_brands_lists_small_companies_the_category_floor_excludes(client, db_session):
    """The 100-unit floor is leak control for a CATEGORY list. With no
    category there is nothing to leak into, so a real 40-unit EV maker --
    the segment a 2W EV buyer researches -- must be findable in All Brands."""
    await _seed(db_session)
    # Its own RTO: persisting a second batch to DL1 would replace the first.
    await db_session.merge(RTO(rto_code="DL2", rto_name="Delhi RTO 2", state_code="DL"))
    await persist_maker_category_batch(
        db_session,
        {"state_name": "Delhi", "rto_code": "DL2", "rto_name": "Delhi RTO 2",
         "records": [{"maker": "QUCEV TECHNOLOGIES PVT LTD", "vehicle_class": BIKE, "count": 40}]},
        state_code="DL", year=2026)
    await db_session.commit()

    assert "QUCEV TECHNOLOGIES PVT LTD" in {m["maker"] for m in await _makers(client)}
    assert "QUCEV TECHNOLOGIES PVT LTD" not in {
        m["maker"] for m in await _makers(client, vehicle_category="Two-Wheeler")
    }


async def test_non_companies_never_appear(client, db_session):
    await _seed(db_session)
    for params in ({}, {"vehicle_category": "Two-Wheeler"}):
        names = {m["maker"] for m in await _makers(client, **params)}
        assert "OTHERS" not in names
        assert "NIC TEST ACCOUNT-1" not in names


async def test_renamed_brand_carries_a_note_despite_vahans_double_space(client, db_session):
    await _seed(db_session)
    by_name = {m["maker"]: m for m in await _makers(client, vehicle_category="Two-Wheeler")}

    assert by_name["HERO HONDA MOTORS  LTD"]["note"] == "Renamed Hero MotoCorp in 2011"
    assert by_name["BMW INDIA PVT LTD"]["note"] is None


async def test_membership_is_national_but_counts_are_scoped(client, db_session):
    """In Maharashtra BMW has 5 bikes -- under the floor locally, but it is a
    two-wheeler maker nationally, so it stays listed. Its count is the
    Maharashtra figure, never the national one, and Delhi-only makers vanish."""
    await _seed(db_session)
    rows = await _makers(client, vehicle_category="Two-Wheeler", state="Maharashtra")

    assert rows == [{"maker": "BMW INDIA PVT LTD", "count": 5, "note": None}]


async def test_category_scoped_account_cannot_see_another_segment(client, db_session):
    """A two-wheeler-scoped account asking for four-wheelers, or for no
    category at all, must still get only two-wheeler makers."""
    await _seed(db_session)
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, email="segment@example.com", role=UserRole.ANALYST, is_active=True,
        scope_type=UserScope.NATIONAL, scope_vehicle_category=VehicleCategoryScope.TWO_WHEELER,
    )
    # No restore needed: the client fixture clears every override at teardown.
    for params in ({}, {"vehicle_category": "Four-Wheeler"}):
        names = {m["maker"] for m in await _makers(client, **params)}
        assert "MARUTI SUZUKI INDIA LTD" not in names, f"four-wheeler maker leaked with {params}"
        assert "HONDA MOTORCYCLE AND SCOOTER INDIA (P) LTD" in names
