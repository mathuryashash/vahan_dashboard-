import os

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.scrape_lock import ScrapeAlreadyRunningError, scrape_write_lock

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://vahan:vahan@127.0.0.1:5432/vahan_test",
)


async def test_second_acquire_on_the_same_key_is_rejected():
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    async with scrape_write_lock(engine, "test:registrations:2026"):
        with pytest.raises(ScrapeAlreadyRunningError):
            async with scrape_write_lock(engine, "test:registrations:2026"):
                pass  # pragma: no cover -- must never get here
    await engine.dispose()


async def test_lock_releases_on_exit_so_a_later_acquire_succeeds():
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    async with scrape_write_lock(engine, "test:registrations:2025"):
        pass
    # Must not raise -- the first `async with` above released the lock on exit.
    async with scrape_write_lock(engine, "test:registrations:2025"):
        pass
    await engine.dispose()


async def test_different_keys_do_not_conflict():
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    async with scrape_write_lock(engine, "test:registrations:maker:2026"):
        # A different dimension/year -- must be allowed to proceed concurrently.
        async with scrape_write_lock(engine, "test:registrations:fuel:2026"):
            pass
    await engine.dispose()


async def test_lock_still_releases_when_the_body_raises():
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    with pytest.raises(ValueError):
        async with scrape_write_lock(engine, "test:registrations:2024"):
            raise ValueError("simulated scrape failure")
    # Must not raise -- the lock must have released even though the body above failed.
    async with scrape_write_lock(engine, "test:registrations:2024"):
        pass
    await engine.dispose()


async def test_sqlite_is_a_no_op():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    # Two concurrent "acquires" on the same key must both succeed -- advisory
    # locks are a Postgres-only concept, SQLite here is dev-only convenience.
    async with scrape_write_lock(engine, "test:registrations:2026"):
        async with scrape_write_lock(engine, "test:registrations:2026"):
            pass
    await engine.dispose()
