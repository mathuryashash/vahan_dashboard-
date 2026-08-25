import time
import pytest
from sqlalchemy import select
from app.models.models import Registration
from app.core.config import settings
from app.services.scraper_service import ScrapeFailedError, persist_rto_batch, run_scraper


async def test_persist_rto_batch_inserts_records(db_session):
    batch = {
        "state_name": "Delhi",
        "rto_code": "DL1",
        "rto_name": "OLD DELHI (MALL ROAD)",
        "records": [
            {"label": "HONDA MOTORCYCLE AND SCOOTER INDIA (P) LTD", "month": 1, "year": 2026, "count": 91},
            {"label": "HONDA MOTORCYCLE AND SCOOTER INDIA (P) LTD", "month": 2, "year": 2026, "count": 34},
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
    assert rows[0].is_supplementary is False


async def test_persist_rto_batch_replaces_prior_year_data(db_session):
    batch = {
        "state_name": "Delhi",
        "rto_code": "DL1",
        "rto_name": "OLD DELHI (MALL ROAD)",
        "records": [{"label": "OLD MAKER", "month": 1, "year": 2026, "count": 5}],
    }
    await persist_rto_batch(db_session, batch, state_code="DL")
    await db_session.commit()

    batch["records"] = [{"label": "NEW MAKER", "month": 1, "year": 2026, "count": 9}]
    await persist_rto_batch(db_session, batch, state_code="DL")
    await db_session.commit()

    result = await db_session.execute(
        select(Registration).where(Registration.rto_code == "DL1", Registration.year == 2026)
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].maker == "NEW MAKER"


async def test_persist_rto_batch_vehicle_class_dimension(db_session):
    batch = {
        "state_name": "Delhi",
        "rto_code": "DL1",
        "rto_name": "OLD DELHI (MALL ROAD)",
        "records": [{"label": "Two-Wheeler", "month": 1, "year": 2026, "count": 40}],
    }
    await persist_rto_batch(db_session, batch, state_code="DL", dimension="vehicle_class")
    await db_session.commit()

    result = await db_session.execute(
        select(Registration).where(Registration.rto_code == "DL1", Registration.year == 2026)
    )
    row = result.scalars().one()
    assert row.vehicle_class == "Two-Wheeler"
    assert row.maker is None
    assert row.fuel_type is None
    assert row.is_supplementary is True


async def test_persist_rto_batch_fuel_dimension(db_session):
    batch = {
        "state_name": "Delhi",
        "rto_code": "DL1",
        "rto_name": "OLD DELHI (MALL ROAD)",
        "records": [{"label": "PETROL", "month": 1, "year": 2026, "count": 25}],
    }
    await persist_rto_batch(db_session, batch, state_code="DL", dimension="fuel")
    await db_session.commit()

    result = await db_session.execute(
        select(Registration).where(Registration.rto_code == "DL1", Registration.year == 2026)
    )
    row = result.scalars().one()
    assert row.fuel_type == "PETROL"
    assert row.vehicle_class == "All"
    assert row.maker is None
    assert row.is_supplementary is True


async def test_persist_rto_batch_dimensions_coexist_independently(db_session):
    """Re-scraping one dimension must not delete another dimension's rows for
    the same RTO/year -- they're separate, additive breakdowns of the same
    underlying registrations, not replacements of each other."""
    maker_batch = {
        "state_name": "Delhi", "rto_code": "DL1", "rto_name": "OLD DELHI (MALL ROAD)",
        "records": [{"label": "HONDA", "month": 1, "year": 2026, "count": 91}],
    }
    vc_batch = {
        "state_name": "Delhi", "rto_code": "DL1", "rto_name": "OLD DELHI (MALL ROAD)",
        "records": [{"label": "Two-Wheeler", "month": 1, "year": 2026, "count": 91}],
    }
    fuel_batch = {
        "state_name": "Delhi", "rto_code": "DL1", "rto_name": "OLD DELHI (MALL ROAD)",
        "records": [{"label": "PETROL", "month": 1, "year": 2026, "count": 91}],
    }
    await persist_rto_batch(db_session, maker_batch, state_code="DL", dimension="maker")
    await persist_rto_batch(db_session, vc_batch, state_code="DL", dimension="vehicle_class")
    await persist_rto_batch(db_session, fuel_batch, state_code="DL", dimension="fuel")
    await db_session.commit()

    # Re-scrape just the vehicle_class dimension again with a different count.
    vc_batch["records"] = [{"label": "Two-Wheeler", "month": 1, "year": 2026, "count": 99}]
    await persist_rto_batch(db_session, vc_batch, state_code="DL", dimension="vehicle_class")
    await db_session.commit()

    result = await db_session.execute(
        select(Registration).where(Registration.rto_code == "DL1", Registration.year == 2026)
    )
    rows = {(r.is_supplementary, r.maker, r.vehicle_class, r.fuel_type): r.count for r in result.scalars().all()}
    assert len(rows) == 3
    assert rows[(False, "HONDA", "All", None)] == 91
    assert rows[(True, None, "Two-Wheeler", None)] == 99  # updated, not duplicated
    assert rows[(True, None, "All", "PETROL")] == 91  # untouched by the vehicle_class re-scrape


async def test_run_scraper_runs_dimensions_concurrently_not_sequentially(monkeypatch):
    """The three dimensions are independent full-India passes -- there's no
    correctness reason to run them one after another, only a historical one.
    A regression here (e.g. reverting to a plain `for` loop over `await`)
    would silently 3x the wall-clock time of every refresh."""
    calls = []

    def fake_dimension_sync(dimension, concurrent_states=1, force=True):
        calls.append((dimension, "start", time.monotonic()))
        time.sleep(0.2)
        calls.append((dimension, "end", time.monotonic()))
        return 0

    monkeypatch.setattr("app.services.scraper_service._run_dimension_sync", fake_dimension_sync)

    start = time.monotonic()
    await run_scraper()
    elapsed = time.monotonic() - start

    assert settings.REFRESH_STATUS == "success"
    assert {c[0] for c in calls} == {"maker", "vehicle_class", "fuel"}
    # Sequential would take >= 0.6s (3 x 0.2s); concurrent finishes near 0.2s.
    assert elapsed < 0.45, f"expected concurrent dimensions to overlap, took {elapsed:.2f}s"


async def test_run_scraper_marks_network_failure_for_retry(monkeypatch):
    monkeypatch.setattr("app.services.scraper_service._run_dimension_sync", lambda dimension, concurrent_states=1, force=True: 1)
    settings.REFRESH_STATUS = "idle"
    settings.REFRESH_ERROR = None

    with pytest.raises(ScrapeFailedError):
        await run_scraper()

    assert settings.REFRESH_STATUS == "retrying"
    assert settings.REFRESH_ERROR == "Scraper subprocess for maker exited with code 1"
