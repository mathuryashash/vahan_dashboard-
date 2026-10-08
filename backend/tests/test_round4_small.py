"""Round 4 / E: small backend items.

- N4: a YoY window that starts after the last complete month is an explicit
  empty answer (totals/growth null + empty_reason), not "0 vs 0, +0.0%".
- data_freshness: no Postgres-only `::timestamptz` on SQLite; a result computed
  across a TTLCache.clear_all() is returned but not cached.
- maker-search cold build: one lock per scope key, not one global lock.
"""
import asyncio
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.cache import TTLCache
from app.models.models import RTO, Registration, State
from app.services import data_freshness, stored_live_service


async def _seed_month(db, year, month, count):
    await db.merge(State(state_code="DL", state_name="Delhi"))
    await db.merge(RTO(rto_code="DL1", rto_name="Test RTO", state_code="DL"))
    db.add(Registration(
        state_code="DL", state_name="Delhi", rto_code="DL1", rto_name="Test RTO", month=month, year=year,
        count=count, vehicle_class="All", maker="HONDA", fuel_type=None, is_supplementary=False,
    ))


async def test_yoy_window_after_last_complete_month_is_explicitly_empty(client, db_session):
    for m in range(1, 13):
        await _seed_month(db_session, 2025, m, 1000)
    for m in range(1, 8):  # 2026 through July only
        await _seed_month(db_session, 2026, m, 1100)
    await db_session.commit()
    r = await client.get("/api/v1/yoy/summary",
                         params={"year_a": 2025, "year_b": 2026, "start_month": 10, "end_month": 12})
    assert r.status_code == 200
    body = r.json()
    assert body["total_2025"] is None and body["total_2026"] is None, "0 vs 0 reads as 'no registrations'"
    assert body["growth_percent"] is None
    assert body["empty_reason"] == "window after last complete month"
    assert body["compare_through_month"] < body["start_month"]


async def test_yoy_window_inside_data_has_no_empty_reason(client, db_session):
    for m in range(1, 13):
        await _seed_month(db_session, 2025, m, 1000)
    for m in range(1, 8):
        await _seed_month(db_session, 2026, m, 1100)
    await db_session.commit()
    body = (await client.get("/api/v1/yoy/summary", params={"year_a": 2025, "year_b": 2026})).json()
    assert body["empty_reason"] is None and body["growth_percent"] == 10.0


async def test_freshness_runs_on_sqlite():
    """`::timestamptz` is Postgres syntax; SQLite dev mode used to raise here."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE registrations (year INT, month INT, recorded_at TIMESTAMP)"))
        await conn.execute(text("CREATE TABLE scrape_quality_log (checked_at TIMESTAMP)"))
        await conn.execute(text("INSERT INTO registrations VALUES (2026, 9, '2026-09-19 10:00:00')"))
        await conn.execute(text("INSERT INTO scrape_quality_log VALUES ('2026-09-18 08:00:00')"))
    async with AsyncSession(engine) as db:
        f = await data_freshness.get_freshness(db, use_cache=False)
    await engine.dispose()
    assert (f.latest_year, f.latest_month) == (2026, 9)
    assert f.last_scrape_at.replace(tzinfo=None) == datetime(2026, 9, 19, 10, 0)
    assert f.last_scrape_at.tzinfo is not None


async def test_freshness_not_cached_across_a_cache_clear(db_session, monkeypatch):
    await _seed_month(db_session, 2025, 3, 10)
    await db_session.commit()
    real_execute = db_session.execute
    calls = {"n": 0}

    async def execute(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            TTLCache.clear_all()  # a scrape finished while we were reading
        return await real_execute(*a, **k)

    monkeypatch.setattr(db_session, "execute", execute)
    await data_freshness.get_freshness(db_session)
    assert data_freshness._cache.get("freshness") is None, "stale pre-clear result must not be cached"
    monkeypatch.setattr(db_session, "execute", real_execute)
    await data_freshness.get_freshness(db_session)
    assert data_freshness._cache.get("freshness") is not None


async def test_allowed_makers_locks_are_per_scope():
    a = stored_live_service._lock_for(("Four-Wheeler", None, None))
    b = stored_live_service._lock_for((None, "UP", None))
    assert a is not b
    assert stored_live_service._lock_for(("Four-Wheeler", None, None)) is a
    # Holding one scope's lock must not block another scope's.
    async with a:
        await asyncio.wait_for(b.acquire(), timeout=0.5)
        b.release()
