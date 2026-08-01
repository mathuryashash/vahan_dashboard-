import os
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.core.migrations import ensure_columns

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://vahan:vahan@127.0.0.1:5432/vahan_test",
)


def _table_name() -> str:
    return f"migration_states_{uuid4().hex}"


async def _columns(conn: AsyncConnection, table_name: str) -> set[str]:
    return await conn.run_sync(
        lambda sync_conn: {column["name"] for column in inspect(sync_conn).get_columns(table_name)}
    )


async def test_ensure_columns_adds_missing_column():
    table_name = _table_name()
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE TABLE {table_name} (state_code TEXT PRIMARY KEY, state_name TEXT)"))

    await ensure_columns(engine, {table_name: {"zone_code": "VARCHAR(10)"}})

    async with engine.begin() as conn:
        assert "zone_code" in await _columns(conn, table_name)
        await conn.execute(text(f"DROP TABLE {table_name}"))
    await engine.dispose()


async def test_ensure_columns_is_idempotent():
    table_name = _table_name()
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE TABLE {table_name} (state_code TEXT PRIMARY KEY, state_name TEXT, zone_code VARCHAR(10))"))

    await ensure_columns(engine, {table_name: {"zone_code": "VARCHAR(10)"}})

    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE {table_name}"))
    await engine.dispose()


async def test_ensure_columns_rejects_invalid_identifiers():
    engine = create_async_engine(TEST_DATABASE_URL, future=True)

    with pytest.raises(ValueError):
        await ensure_columns(engine, {"states; DROP TABLE states": {"zone_code": "VARCHAR(10)"}})

    with pytest.raises(ValueError):
        await ensure_columns(engine, {"states": {"zone code": "VARCHAR(10)"}})

    await engine.dispose()


async def test_ensure_columns_tolerates_concurrent_duplicate_column(monkeypatch):
    table_name = _table_name()
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE TABLE {table_name} (state_code TEXT PRIMARY KEY, state_name TEXT)"))

    original_execute = AsyncConnection.execute

    async def fake_execute(self, statement, *args, **kwargs):
        sql = str(statement)
        if "ALTER TABLE" in sql:
            raise OperationalError(sql, {}, Exception("column zone_code already exists"))
        return await original_execute(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncConnection, "execute", fake_execute)

    await ensure_columns(engine, {table_name: {"zone_code": "VARCHAR(10)"}})
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE {table_name}"))
    await engine.dispose()
