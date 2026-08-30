"""Tests for the Maker x Fuel cross-tab: persistence and the
/categories/maker-fuel-breakdown endpoint. Same shape as
test_maker_category.py/test_fuel_category.py -- see docs/superpowers/specs/
2026-08-25-maker-category-crosstab-design.md. Fixes the "engine type +
brand/OEM" combination showing 0: a maker name and a real fuel_type never
coexist on the same Registration row (see Registration.is_supplementary)."""
from app.models.models import MakerFuelTotal
from app.services.scraper_service import persist_maker_fuel_batch


async def _seed_maker_fuel(db_session):
    batch = {
        "state_name": "Delhi", "rto_code": "DL1", "rto_name": "Test RTO",
        "records": [
            {"maker": "HONDA", "fuel_type": "PETROL", "count": 70},
            {"maker": "HONDA", "fuel_type": "ELECTRIC(BOV)", "count": 10},
            {"maker": "TVS", "fuel_type": "PETROL", "count": 40},
        ],
    }
    await persist_maker_fuel_batch(db_session, batch, state_code="DL", year=2026)
    await db_session.commit()


async def test_persist_maker_fuel_batch_stores_raw_fuel_type(db_session):
    await _seed_maker_fuel(db_session)

    from sqlalchemy import select
    result = await db_session.execute(
        select(MakerFuelTotal.maker, MakerFuelTotal.fuel_type, MakerFuelTotal.count)
        .order_by(MakerFuelTotal.maker, MakerFuelTotal.fuel_type)
    )
    rows = result.all()
    assert rows == [
        ("HONDA", "ELECTRIC(BOV)", 10),
        ("HONDA", "PETROL", 70),
        ("TVS", "PETROL", 40),
    ]


async def test_persist_maker_fuel_batch_replaces_existing_rto_year(db_session):
    await _seed_maker_fuel(db_session)
    batch = {
        "state_name": "Delhi", "rto_code": "DL1", "rto_name": "Test RTO",
        "records": [{"maker": "HONDA", "fuel_type": "PETROL", "count": 99}],
    }
    await persist_maker_fuel_batch(db_session, batch, state_code="DL", year=2026)
    await db_session.commit()

    from sqlalchemy import select, func
    result = await db_session.execute(select(func.count()).select_from(MakerFuelTotal))
    assert result.scalar() == 1


async def test_maker_fuel_breakdown_ranks_makers_within_fuel_group(client, db_session):
    """This is the exact combination users reported as broken: selecting an
    engine type (ICE/Hybrid/EV) together with a brand/OEM."""
    await _seed_maker_fuel(db_session)  # ICE (petrol): HONDA=70, TVS=40; EV: HONDA=10

    response = await client.get(
        "/api/v1/categories/maker-fuel-breakdown",
        params={"year": 2026, "fuel_group": "ICE"},
    )
    assert response.status_code == 200
    rows = {r["maker"]: r["count"] for r in response.json()}
    assert rows == {"HONDA": 70, "TVS": 40}


async def test_maker_fuel_breakdown_ranks_fuel_groups_within_maker(client, db_session):
    await _seed_maker_fuel(db_session)

    response = await client.get(
        "/api/v1/categories/maker-fuel-breakdown",
        params={"year": 2026, "maker": "HONDA"},
    )
    assert response.status_code == 200
    rows = {r["fuel_group"]: r["count"] for r in response.json()}
    assert rows == {"ICE": 70, "EV": 10}
