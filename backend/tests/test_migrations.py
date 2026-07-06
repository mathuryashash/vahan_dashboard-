import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
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
