"""Round 4 / A: fuel groups for Maker Lookup / Top Makers, and the
/live-query/maker-options dropdown that lists only makers with stored
registrations for the chosen state + fuel group + year, in the caller's scope.

Seeds reuse test_stored_live's sibling rows (MH1 next to MH2, Delhi next to
Maharashtra) plus multi-label fuels, so a missing clamp or a raw label left out
of its group changes a number.
"""
import pytest

from app.core.rate_limit import limiter
from app.models.models import MakerFuelTotal
from app.services import fuel_groups
from tests.test_stored_live import (
    FOUR_WHEELER, HERO, HONDA, MH1_RTO, MH_STATE, TATA, _get, _login_as, _mft, _no_live_site, _seed,  # noqa: F401
)


@pytest.fixture(autouse=True)
def _reset_slowapi():
    """/maker and /leaderboard are rate-limited per IP; every test here shares
    127.0.0.1, so without a reset this module's calls starve the next one's."""
    limiter.reset()
    yield
    limiter.reset()


# ---- the mapping --------------------------------------------------------------

@pytest.mark.parametrize("raw, group", [
    ("PETROL", "Petrol"), ("PETROL(E20)", "Petrol"), ("PETROL/ETHANOL", "Petrol"), ("PETROL/METHANOL", "Petrol"),
    ("DIESEL", "Diesel"), ("FLEX-FUEL(BIO-DIESEL)", "Diesel"),
    ("CNG ONLY", "CNG/LPG"), ("PETROL/CNG", "CNG/LPG"), ("PETROL(E20)/CNG", "CNG/LPG"), ("LPG ONLY", "CNG/LPG"),
    ("PETROL/LPG", "CNG/LPG"), ("DUAL DIESEL/LNG", "CNG/LPG"), ("LNG", "CNG/LPG"), ("HCNG", "CNG/LPG"),
    ("PURE EV", "Electric"), ("ELECTRIC(BOV)", "Electric"), ("FUEL CELL HYDROGEN", "Electric"),
    ("STRONG HYBRID EV", "Hybrid"), ("PLUG-IN HYBRID EV", "Hybrid"), ("PETROL(E20)/HYBRID/CNG", "Hybrid"),
    ("DIESEL/HYBRID", "Hybrid"),
    ("ETHANOL(E100)", "Other"), ("SOLAR", "Other"), ("NOT APPLICABLE", "Other"), (None, "Other"),
    ("pure ev", "Electric"),
])
def test_group_of(raw, group):
    assert fuel_groups.group_of(raw) == group


def test_every_known_label_lands_in_exactly_one_group():
    table = fuel_groups.mapping_table()
    assert [row["group"] for row in table] == list(fuel_groups.FUEL_GROUPS)
    flat = [label for row in table for label in row["raw_labels"]]
    assert sorted(flat) == sorted(fuel_groups.KNOWN_RAW_FUELS)


def test_normalize_group():
    assert fuel_groups.normalize_group("cng/lpg") == "CNG/LPG"
    assert fuel_groups.normalize_group("") is None
    with pytest.raises(ValueError):
        fuel_groups.normalize_group("ICE")


# ---- endpoints ----------------------------------------------------------------

async def _seed_multi(db):
    await _seed(db)
    db.add_all([
        _mft("MH1", "MH", HONDA, "PETROL(E20)", 10),
        _mft("MH1", "MH", HONDA, "PETROL/ETHANOL", 3),
        _mft("MH1", "MH", HONDA, "STRONG HYBRID EV", 25),
        _mft("MH1", "MH", TATA, "PURE EV", 8), _mft("MH2", "MH", TATA, "ELECTRIC(BOV)", 2),
        _mft("MH1", "MH", TATA, "PETROL(E20)/CNG", 5),
    ])
    await db.commit()


async def test_fuel_groups_listing(client):
    body = await _get(client, "fuel-groups")
    assert [r["group"] for r in body] == list(fuel_groups.FUEL_GROUPS)


async def test_maker_options_lists_only_makers_with_that_fuel(client, db_session):
    await _seed_multi(db_session)
    diesel = await _get(client, "maker-options", state_code="MH", year=2025, fuel_group="Diesel")
    # Hero has no diesel in Maharashtra, so it is simply not offered.
    assert [m["maker"] for m in diesel["makers"]] == [TATA]
    petrol = await _get(client, "maker-options", state_code="MH", year=2025, fuel_group="petrol")
    assert petrol["fuel_group"] == "Petrol"
    # Sorted by volume; HONDA sums PETROL 90+700 + PETROL(E20) 10 + PETROL/ETHANOL 3.
    assert petrol["makers"] == [{"maker": HONDA, "total": 803}, {"maker": HERO, "total": 400}]
    ev = await _get(client, "maker-options", state_code="MH", year=2025, fuel_group="Electric")
    assert ev["makers"] == [{"maker": TATA, "total": 10}]  # PURE EV 8 + ELECTRIC(BOV) 2


async def test_maker_options_without_fuel_uses_category_totals(client, db_session):
    await _seed_multi(db_session)
    body = await _get(client, "maker-options", state_code="MH", year=2025)
    # MCT: HERO 500, HONDA 30+70+300, TATA 40 (Delhi's 9999 TATA excluded).
    assert body["makers"] == [{"maker": HERO, "total": 500}, {"maker": HONDA, "total": 400},
                              {"maker": TATA, "total": 40}]


async def test_maker_options_rto_scope(client, db_session):
    await _seed_multi(db_session)
    _login_as(**MH1_RTO)
    body = await _get(client, "maker-options", state_code="MH", year=2025, fuel_group="Petrol")
    assert body["rto"] == "MH1"
    assert {m["maker"]: m["total"] for m in body["makers"]} == {HONDA: 103, HERO: 400}  # not 803


async def test_maker_options_state_scope_and_category_scope(client, db_session):
    await _seed_multi(db_session)
    _login_as(**MH_STATE)
    r = await client.get("/api/v1/live-query/maker-options", params={"state_code": "DL", "year": 2025})
    assert r.status_code == 403
    _login_as(**FOUR_WHEELER)
    body = await _get(client, "maker-options", state_code="MH", year=2025)
    assert {m["maker"] for m in body["makers"]} == {HONDA, TATA}  # Hero's 2W not offered
    refused = await _get(client, "maker-options", state_code="MH", year=2025, fuel_group="Petrol")
    assert refused["makers"] == [] and refused["unanswerable_reason"]


async def test_maker_options_rejects_unknown_group(client, db_session):
    r = await client.get("/api/v1/live-query/maker-options",
                         params={"state_code": "MH", "year": 2025, "fuel_group": "ICE"})
    assert r.status_code == 422


async def test_maker_lookup_by_group_sums_raw_fuels(client, db_session):
    await _seed_multi(db_session)
    body = await _get(client, "maker", state_code="MH", year=2025, maker=HONDA, fuel_group="Petrol")
    assert body["fuel_group"] == "Petrol" and body["grain"] == "year"
    by_label = {r["category"]: r["count"] for r in body["records"]}
    assert by_label == {"PETROL": 790, "PETROL(E20)": 10, "PETROL/ETHANOL": 3}
    # Aggregation == sum of the raw labels in the group, straight from the table.
    rows = (await db_session.execute(
        MakerFuelTotal.__table__.select().where(MakerFuelTotal.maker == HONDA, MakerFuelTotal.state_code == "MH")
    )).all()
    assert sum(by_label.values()) == sum(r.count for r in rows if fuel_groups.group_of(r.fuel_type) == "Petrol")
    hybrid = await _get(client, "maker", state_code="MH", year=2025, maker=HONDA, fuel_group="Hybrid")
    assert [r["count"] for r in hybrid["records"]] == [25]


async def test_leaderboard_by_group(client, db_session):
    await _seed_multi(db_session)
    body = await _get(client, "leaderboard", state_code="MH", year=2025, fuel_group="CNG/LPG")
    assert body["makers"] == [{"maker": TATA, "total": 5}]
    body = await _get(client, "leaderboard", state_code="MH", year=2025, fuel_group="Petrol", limit=1)
    assert body["makers"] == [{"maker": HONDA, "total": 803}]
    _login_as(**MH1_RTO)
    body = await _get(client, "leaderboard", state_code="MH", year=2025, fuel_group="Petrol")
    assert body["makers"][0] == {"maker": HERO, "total": 400}  # MH2's 700 Honda excluded
