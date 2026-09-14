import pytest
from sqlalchemy import select

from app.models.models import State, StateMonthCategoryTotal
from app.services.scraper_service import persist_state_month_category_batch


@pytest.fixture(autouse=True)
async def _seed_state(db_session):
    await db_session.merge(State(state_code="BR", state_name="Bihar"))
    await db_session.commit()


async def test_persist_state_month_category_batch_inserts_records(db_session):
    records = [
        {"month": 1, "category": "TWO WHEELER(NT)", "count": 1000},
        {"month": 1, "category": "FOUR WHEELER", "count": 200},
    ]
    await persist_state_month_category_batch(db_session, "BR", "Bihar", 2024, records)
    await db_session.commit()

    rows = (await db_session.execute(
        select(StateMonthCategoryTotal).where(StateMonthCategoryTotal.state_code == "BR")
    )).scalars().all()
    assert len(rows) == 2
    assert {r.count for r in rows} == {1000, 200}
    assert rows[0].state_name == "Bihar"
    assert rows[0].year == 2024


async def test_persist_state_month_category_batch_replaces_prior_year_data(db_session):
    await persist_state_month_category_batch(
        db_session, "BR", "Bihar", 2024, [{"month": 1, "category": "TWO WHEELER(NT)", "count": 1000}],
    )
    await db_session.commit()

    await persist_state_month_category_batch(
        db_session, "BR", "Bihar", 2024, [{"month": 2, "category": "FOUR WHEELER", "count": 50}],
    )
    await db_session.commit()

    rows = (await db_session.execute(
        select(StateMonthCategoryTotal).where(StateMonthCategoryTotal.state_code == "BR", StateMonthCategoryTotal.year == 2024)
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].month == 2
    assert rows[0].category == "FOUR WHEELER"


async def test_persist_state_month_category_batch_keeps_other_years_untouched(db_session):
    await persist_state_month_category_batch(
        db_session, "BR", "Bihar", 2023, [{"month": 1, "category": "TWO WHEELER(NT)", "count": 500}],
    )
    await db_session.commit()

    await persist_state_month_category_batch(
        db_session, "BR", "Bihar", 2024, [{"month": 1, "category": "TWO WHEELER(NT)", "count": 1000}],
    )
    await db_session.commit()

    rows = (await db_session.execute(
        select(StateMonthCategoryTotal).where(StateMonthCategoryTotal.state_code == "BR")
    )).scalars().all()
    assert {(r.year, r.count) for r in rows} == {(2023, 500), (2024, 1000)}
