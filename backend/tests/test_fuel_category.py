"""Tests for the Fuel-group x Vehicle Category cross-tab: persistence and the
/categories/fuel-category-breakdown endpoint. Same shape as
test_maker_category.py -- see docs/superpowers/specs/
2026-08-25-maker-category-crosstab-design.md."""
from app.models.models import FuelCategoryTotal
from app.services.scraper_service import persist_fuel_category_batch


async def _seed_fuel_category(db_session):
    batch = {
        "state_name": "Delhi", "rto_code": "DL1", "rto_name": "Test RTO",
        "records": [
            {"fuel_type": "ELECTRIC(BOV)", "vehicle_class": "M-CYCLE/SCOOTER", "count": 70},
            {"fuel_type": "PETROL", "vehicle_class": "M-CYCLE/SCOOTER", "count": 30},
            {"fuel_type": "PETROL", "vehicle_class": "MOTOR CAR", "count": 40},
        ],
    }
    await persist_fuel_category_batch(db_session, batch, state_code="DL", year=2026)
    await db_session.commit()


async def test_persist_fuel_category_batch_classifies_vehicle_category(db_session):
    await _seed_fuel_category(db_session)

    from sqlalchemy import select
    result = await db_session.execute(
        select(FuelCategoryTotal.fuel_type, FuelCategoryTotal.vehicle_category, FuelCategoryTotal.count)
        .order_by(FuelCategoryTotal.fuel_type, FuelCategoryTotal.vehicle_category)
    )
    rows = result.all()
    assert rows == [
        ("ELECTRIC(BOV)", "Two-Wheeler", 70),
        ("PETROL", "Four-Wheeler", 40),
        ("PETROL", "Two-Wheeler", 30),
    ]


async def test_persist_fuel_category_batch_replaces_existing_rto_year(db_session):
    await _seed_fuel_category(db_session)
    batch = {
        "state_name": "Delhi", "rto_code": "DL1", "rto_name": "Test RTO",
        "records": [{"fuel_type": "PETROL", "vehicle_class": "M-CYCLE/SCOOTER", "count": 99}],
    }
    await persist_fuel_category_batch(db_session, batch, state_code="DL", year=2026)
    await db_session.commit()

    from sqlalchemy import select, func
    result = await db_session.execute(select(func.count()).select_from(FuelCategoryTotal))
    assert result.scalar() == 1


async def test_fuel_category_breakdown_ranks_fuel_groups_within_category(client, db_session):
    await _seed_fuel_category(db_session)  # Two-Wheeler: EV=70, Petrol=30

    response = await client.get(
        "/api/v1/categories/fuel-category-breakdown",
        params={"year": 2026, "vehicle_category": "Two-Wheeler"},
    )
    assert response.status_code == 200
    rows = {r["fuel_group"]: r["count"] for r in response.json()}
    assert rows == {"EV": 70, "ICE": 30}


async def test_fuel_category_breakdown_ranks_categories_within_fuel_group(client, db_session):
    await _seed_fuel_category(db_session)  # ICE (petrol): Two-Wheeler=30, Four-Wheeler=40

    response = await client.get(
        "/api/v1/categories/fuel-category-breakdown",
        params={"year": 2026, "fuel_group": "ICE"},
    )
    assert response.status_code == 200
    rows = {r["vehicle_category"]: r["count"] for r in response.json()}
    assert rows == {"Two-Wheeler": 30, "Four-Wheeler": 40}
