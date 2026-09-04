"""Tests for the cross-dimension consistency check (app.services.scrape_quality):
maker/vehicle_class/fuel passes are three independent scrapes of the same
underlying registrations for a given (RTO, month), so their totals should
agree within MAX_PCT_DIFF."""
import sqlalchemy as sa

from app.models.models import Registration, ScrapeQualityLog
from app.services.scrape_quality import check_scrape_quality


def _row(*, is_supplementary, fuel_type=None, vehicle_class="All", maker=None, count):
    return Registration(
        state_code="DL", state_name="Delhi", rto_code="DL1", rto_name="Test RTO",
        year=2026, month=1, vehicle_class=vehicle_class, maker=maker, fuel_type=fuel_type,
        count=count, is_supplementary=is_supplementary,
    )


async def test_agreeing_dimensions_are_marked_clean(db_session):
    # All three passes report ~1000 for the same RTO/month.
    db_session.add_all([
        _row(is_supplementary=False, maker="HONDA", count=1000),
        _row(is_supplementary=True, vehicle_class="Two-Wheeler", count=1005),
        _row(is_supplementary=True, fuel_type="PETROL", vehicle_class="All", count=995),
    ])
    await db_session.commit()

    summary = await check_scrape_quality(db_session, 2026)
    assert summary["cells_checked"] == 1
    assert summary["cells_clean"] == 1

    log = (await db_session.execute(sa.select(ScrapeQualityLog))).scalar_one()
    assert log.is_clean is True
    assert log.max_pct_diff < 2.0


async def test_disagreeing_dimensions_are_flagged_dirty(db_session):
    # Fuel pass wildly disagrees with the other two -- stale/corrupted scrape.
    db_session.add_all([
        _row(is_supplementary=False, maker="HONDA", count=1000),
        _row(is_supplementary=True, vehicle_class="Two-Wheeler", count=1000),
        _row(is_supplementary=True, fuel_type="PETROL", vehicle_class="All", count=200),
    ])
    await db_session.commit()

    summary = await check_scrape_quality(db_session, 2026)
    assert summary["cells_checked"] == 1
    assert summary["cells_clean"] == 0
    assert summary["pct_clean"] == 0.0


async def test_cell_with_only_one_dimension_present_is_skipped_not_flagged(db_session):
    # A coverage gap (only the maker pass has scraped this RTO/month so
    # far) isn't the same thing as a disagreement -- with nothing to
    # compare it against, it shouldn't count against the clean percentage
    # either way.
    db_session.add(_row(is_supplementary=False, maker="HONDA", count=1000))
    await db_session.commit()

    summary = await check_scrape_quality(db_session, 2026)
    assert summary["cells_checked"] == 0
    assert summary["cells_clean"] == 0
    assert summary["pct_clean"] is None


async def test_rerunning_check_replaces_prior_results_for_that_year(db_session):
    db_session.add_all([
        _row(is_supplementary=False, maker="HONDA", count=1000),
        _row(is_supplementary=True, vehicle_class="Two-Wheeler", count=1000),
    ])
    await db_session.commit()

    await check_scrape_quality(db_session, 2026)
    await check_scrape_quality(db_session, 2026)

    count = (await db_session.execute(sa.select(sa.func.count()).select_from(ScrapeQualityLog))).scalar()
    assert count == 1
