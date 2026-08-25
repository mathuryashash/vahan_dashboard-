"""Tests for the Maker x Vehicle Category cross-tab: persistence and the
/categories/maker-category-breakdown endpoint. See docs/superpowers/specs/
2026-08-25-maker-category-crosstab-design.md."""
from app.models.models import MakerCategoryTotal
from app.services.scraper_service import persist_maker_category_batch


async def _seed_maker_category(db_session):
    batch = {
        "state_name": "Delhi", "rto_code": "DL1", "rto_name": "Test RTO",
        "records": [
            {"maker": "HONDA", "vehicle_class": "M-CYCLE/SCOOTER", "count": 70},
            {"maker": "HONDA", "vehicle_class": "MOTOR CAR", "count": 10},
            {"maker": "TVS", "vehicle_class": "M-CYCLE/SCOOTER", "count": 40},
        ],
    }
    await persist_maker_category_batch(db_session, batch, state_code="DL", year=2026)
    await db_session.commit()


async def test_persist_maker_category_batch_classifies_vehicle_category(db_session):
    await _seed_maker_category(db_session)

    from sqlalchemy import select
    result = await db_session.execute(
        select(MakerCategoryTotal.maker, MakerCategoryTotal.vehicle_category, MakerCategoryTotal.count)
        .order_by(MakerCategoryTotal.maker, MakerCategoryTotal.vehicle_category)
    )
    rows = result.all()
    assert rows == [
        ("HONDA", "Four-Wheeler", 10),
        ("HONDA", "Two-Wheeler", 70),
        ("TVS", "Two-Wheeler", 40),
    ]


async def test_persist_maker_category_batch_replaces_existing_rto_year(db_session):
    await _seed_maker_category(db_session)
    # Re-scrape the same RTO/year with different numbers -- must replace, not add.
    batch = {
        "state_name": "Delhi", "rto_code": "DL1", "rto_name": "Test RTO",
        "records": [{"maker": "HONDA", "vehicle_class": "M-CYCLE/SCOOTER", "count": 99}],
    }
    await persist_maker_category_batch(db_session, batch, state_code="DL", year=2026)
    await db_session.commit()

    from sqlalchemy import select, func
    result = await db_session.execute(select(func.count()).select_from(MakerCategoryTotal))
    assert result.scalar() == 1


async def test_maker_category_breakdown_ranks_makers_within_category(client, db_session):
    await _seed_maker_category(db_session)

    response = await client.get(
        "/api/v1/categories/maker-category-breakdown",
        params={"year": 2026, "vehicle_category": "Two-Wheeler"},
    )
    assert response.status_code == 200
    rows = {r["maker"]: r["count"] for r in response.json()}
    assert rows == {"HONDA": 70, "TVS": 40}


async def test_maker_category_breakdown_ranks_categories_within_maker(client, db_session):
    await _seed_maker_category(db_session)

    response = await client.get(
        "/api/v1/categories/maker-category-breakdown",
        params={"year": 2026, "maker": "HONDA"},
    )
    assert response.status_code == 200
    rows = {r["vehicle_category"]: r["count"] for r in response.json()}
    assert rows == {"Two-Wheeler": 70, "Four-Wheeler": 10}
