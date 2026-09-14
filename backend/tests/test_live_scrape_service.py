import pytest
from sqlalchemy import select

from app.models.models import MakerLiveQueryCache, State
from app.services.live_scrape_service import (
    ALL_FUEL_SENTINEL, UnknownStateCodeError, _normalize, _read_cache, _write_cache, get_or_scrape_maker_query,
    get_top_makers_leaderboard,
)


@pytest.fixture(autouse=True)
async def _seed_state(db_session):
    await db_session.merge(State(state_code="BR", state_name="Bihar"))
    await db_session.commit()


async def test_read_cache_returns_none_when_never_scraped(db_session):
    result = await _read_cache(db_session, "BR", 2024, "HONDA", ALL_FUEL_SENTINEL)
    assert result is None


async def test_write_then_read_cache_round_trips_records(db_session):
    records = [
        {"month": 1, "category": "TWO WHEELER(NT)", "count": 500},
        {"month": 2, "category": "TWO WHEELER(NT)", "count": 450},
    ]
    await _write_cache(db_session, "BR", "Bihar", 2024, "HONDA", ALL_FUEL_SENTINEL, records)
    await db_session.commit()

    result = await _read_cache(db_session, "BR", 2024, "HONDA", ALL_FUEL_SENTINEL)
    assert result == records


async def test_write_cache_with_no_records_stores_empty_marker(db_session):
    await _write_cache(db_session, "BR", "Bihar", 2024, "HONDA", "PURE EV", [])
    await db_session.commit()

    rows = (await db_session.execute(
        select(MakerLiveQueryCache).where(MakerLiveQueryCache.maker == "HONDA", MakerLiveQueryCache.fuel == "PURE EV")
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].category == "__EMPTY__"

    # A confirmed-empty combo reads back as an empty list, not None (None
    # means "never scraped" -- the whole point of the marker is telling
    # those two cases apart).
    result = await _read_cache(db_session, "BR", 2024, "HONDA", "PURE EV")
    assert result == []


async def test_cache_is_scoped_per_fuel_not_shared_across_fuels(db_session):
    await _write_cache(db_session, "BR", "Bihar", 2024, "HONDA", "PETROL", [{"month": 1, "category": "TWO WHEELER(NT)", "count": 500}])
    await db_session.commit()

    # A different fuel for the same maker/state/year is a cache miss, not a
    # stale hit against PETROL's data.
    result = await _read_cache(db_session, "BR", 2024, "HONDA", "DIESEL")
    assert result is None


async def test_cache_is_scoped_per_maker_not_shared_across_makers(db_session):
    await _write_cache(db_session, "BR", "Bihar", 2024, "HONDA", ALL_FUEL_SENTINEL, [{"month": 1, "category": "TWO WHEELER(NT)", "count": 500}])
    await db_session.commit()

    result = await _read_cache(db_session, "BR", 2024, "MARUTI SUZUKI", ALL_FUEL_SENTINEL)
    assert result is None


def test_normalize_collapses_case_and_whitespace():
    assert _normalize(" honda ") == "HONDA"
    assert _normalize("Honda") == "HONDA"
    assert _normalize("HONDA") == "HONDA"


async def test_get_or_scrape_raises_for_unknown_state_code_before_any_scrape(db_session):
    # No State row for 'ZZ' -- must fail fast (no network call) rather than
    # paying a live scrape for a state_code that can never resolve to a name.
    with pytest.raises(UnknownStateCodeError):
        await get_or_scrape_maker_query(db_session, "ZZ", 2024, "HONDA")


async def test_write_cache_is_idempotent_for_repeated_writes_same_key(db_session):
    # The current-year path in get_or_scrape_maker_query calls _write_cache
    # more than once for the same key across separate requests -- must
    # replace, not collide with idx_mlqc_natural_key on the second write.
    await _write_cache(db_session, "BR", "Bihar", 2024, "HONDA", "PETROL", [{"month": 1, "category": "TWO WHEELER(NT)", "count": 500}])
    await db_session.commit()
    await _write_cache(db_session, "BR", "Bihar", 2024, "HONDA", "PETROL", [{"month": 1, "category": "TWO WHEELER(NT)", "count": 600}])
    await db_session.commit()

    result = await _read_cache(db_session, "BR", 2024, "HONDA", "PETROL")
    assert result == [{"month": 1, "category": "TWO WHEELER(NT)", "count": 600}]


async def test_leaderboard_raises_for_unknown_state_code_before_any_query(db_session):
    # Same fast-fail contract as get_or_scrape_maker_query -- no maker
    # ranking query, no live scrape, for a state_code that isn't real.
    with pytest.raises(UnknownStateCodeError):
        await get_top_makers_leaderboard(db_session, "ZZ", 2024)
