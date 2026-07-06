import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from app.core.migrations import ensure_columns


async def test_ensure_columns_adds_missing_column():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE states (state_code TEXT PRIMARY KEY, state_name TEXT)"))

    await ensure_columns(engine, {"states": {"zone_code": "VARCHAR(10)"}})

    async with engine.begin() as conn:
        result = await conn.execute(text("PRAGMA table_info(states)"))
        columns = {row[1] for row in result.fetchall()}
    assert "zone_code" in columns
    await engine.dispose()


async def test_ensure_columns_is_idempotent():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE states (state_code TEXT PRIMARY KEY, state_name TEXT, zone_code VARCHAR(10))"))

    # Should not raise even though the column already exists
    await ensure_columns(engine, {"states": {"zone_code": "VARCHAR(10)"}})
    await engine.dispose()


async def test_ensure_columns_rejects_invalid_identifiers():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE states (state_code TEXT PRIMARY KEY, state_name TEXT)"))

    with pytest.raises(ValueError):
        await ensure_columns(engine, {"states; DROP TABLE states": {"zone_code": "VARCHAR(10)"}})

    with pytest.raises(ValueError):
        await ensure_columns(engine, {"states": {"zone code": "VARCHAR(10)"}})

    await engine.dispose()


async def test_ensure_columns_tolerates_concurrent_duplicate_column(monkeypatch):
    """Simulates the race where another worker's PRAGMA check also missed the
    column and it wins the ALTER TABLE first -- our ALTER then fails with
    "duplicate column name", which ensure_columns must swallow, not raise."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE states (state_code TEXT PRIMARY KEY, state_name TEXT)"))

    original_execute = AsyncConnection.execute

    async def fake_execute(self, statement, *args, **kwargs):
        sql = str(statement)
        if "PRAGMA table_info" in sql:
            class FakeResult:
                def fetchall(self):
                    return []  # our check says the column is missing...

            return FakeResult()
        if "ALTER TABLE" in sql:
            # ...but another worker already added it concurrently.
            raise OperationalError(sql, {}, Exception("duplicate column name: zone_code"))
        return await original_execute(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncConnection, "execute", fake_execute)

    # Should not raise -- the race is tolerated.
    await ensure_columns(engine, {"states": {"zone_code": "VARCHAR(10)"}})
    await engine.dispose()
