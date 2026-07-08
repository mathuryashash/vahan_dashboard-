from sqlalchemy import select
from app.models.models import Registration
from app.services.scraper_service import persist_rto_batch


async def test_persist_rto_batch_inserts_records(db_session):
    batch = {
        "state_name": "Delhi",
        "rto_code": "DL1",
        "rto_name": "OLD DELHI (MALL ROAD)",
        "records": [
            {"maker": "HONDA MOTORCYCLE AND SCOOTER INDIA (P) LTD", "month": 1, "year": 2026, "count": 91},
            {"maker": "HONDA MOTORCYCLE AND SCOOTER INDIA (P) LTD", "month": 2, "year": 2026, "count": 34},
        ],
    }
    await persist_rto_batch(db_session, batch, state_code="DL")
    await db_session.commit()

    result = await db_session.execute(
        select(Registration).where(Registration.rto_code == "DL1")
    )
    rows = result.scalars().all()
    assert len(rows) == 2
    assert {r.count for r in rows} == {91, 34}
    assert rows[0].state_name == "Delhi"
    assert rows[0].vehicle_class == "All"


async def test_persist_rto_batch_replaces_prior_year_data(db_session):
    batch = {
        "state_name": "Delhi",
        "rto_code": "DL1",
        "rto_name": "OLD DELHI (MALL ROAD)",
        "records": [{"maker": "OLD MAKER", "month": 1, "year": 2026, "count": 5}],
    }
    await persist_rto_batch(db_session, batch, state_code="DL")
    await db_session.commit()

    batch["records"] = [{"maker": "NEW MAKER", "month": 1, "year": 2026, "count": 9}]
    await persist_rto_batch(db_session, batch, state_code="DL")
    await db_session.commit()

    result = await db_session.execute(
        select(Registration).where(Registration.rto_code == "DL1", Registration.year == 2026)
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].maker == "NEW MAKER"
