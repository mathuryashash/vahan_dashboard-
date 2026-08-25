import os
from uuid import uuid4

import pytest
from sqlalchemy import Column, Index, Integer, MetaData, String, Table, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.core.migrations import ensure_analyzed, ensure_columns, ensure_indexes, ensure_vehicle_category_backfilled

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


async def test_ensure_indexes_creates_missing_index_and_is_idempotent():
    table_name = _table_name()
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    metadata = MetaData()
    table = Table(
        table_name, metadata,
        Column("id", Integer, primary_key=True),
        Column("state_code", String),
        Index(f"ix_{table_name}_state_code", "state_code"),
    )
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: table.create(sync_conn, checkfirst=True))

    await ensure_indexes(engine, metadata)
    await ensure_indexes(engine, metadata)  # idempotent -- must not raise on a second pass

    async with engine.begin() as conn:
        indexnames = await conn.run_sync(lambda sync_conn: {i["name"] for i in inspect(sync_conn).get_indexes(table_name)})
        assert f"ix_{table_name}_state_code" in indexnames
        await conn.execute(text(f"DROP TABLE {table_name}"))
    await engine.dispose()


async def test_ensure_analyzed_fixes_unanalyzed_table_with_rows():
    table_name = _table_name()
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE TABLE {table_name} (id SERIAL PRIMARY KEY, val INT)"))
        # A fresh table's reltuples is 0/-1 until something runs ANALYZE --
        # this is the exact bug ensure_analyzed exists to catch.
        await conn.execute(text(f"INSERT INTO {table_name} (val) SELECT generate_series(1, 500)"))

    async with engine.connect() as conn:
        reltuples_before = (
            await conn.execute(text("SELECT reltuples FROM pg_class WHERE relname = :t"), {"t": table_name})
        ).scalar()
    assert reltuples_before is not None and reltuples_before <= 0

    await ensure_analyzed(engine, [table_name])

    async with engine.connect() as conn:
        reltuples_after = (
            await conn.execute(text("SELECT reltuples FROM pg_class WHERE relname = :t"), {"t": table_name})
        ).scalar()
    assert reltuples_after == 500

    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE {table_name}"))
    await engine.dispose()


async def test_ensure_analyzed_skips_genuinely_empty_table():
    table_name = _table_name()
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE TABLE {table_name} (id SERIAL PRIMARY KEY)"))

    await ensure_analyzed(engine, [table_name])  # must not raise for a table with no rows

    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE {table_name}"))
    await engine.dispose()


async def test_ensure_analyzed_rejects_invalid_identifier():
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    with pytest.raises(ValueError):
        await ensure_analyzed(engine, ["states; DROP TABLE states"])
    await engine.dispose()


async def test_ensure_vehicle_category_backfilled_classifies_existing_rows():
    table_name = _table_name()
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    async with engine.begin() as conn:
        await conn.execute(text(
            f"CREATE TABLE {table_name} (id SERIAL PRIMARY KEY, vehicle_class TEXT NOT NULL, "
            f"vehicle_category TEXT, commercial_tier TEXT)"
        ))
        await conn.execute(text(
            f"INSERT INTO {table_name} (vehicle_class) VALUES "
            f"('M-CYCLE/SCOOTER'), ('MOTOR CAR'), ('Heavy Truck'), ('AGRICULTURAL TRACTOR')"
        ))

    await ensure_vehicle_category_backfilled(engine, table_name=table_name)

    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            f"SELECT vehicle_class, vehicle_category, commercial_tier FROM {table_name} ORDER BY id"
        ))).all()
    assert rows == [
        ("M-CYCLE/SCOOTER", "Two-Wheeler", None),
        ("MOTOR CAR", "Four-Wheeler", None),
        ("Heavy Truck", "Commercial Vehicle", "HCV"),
        ("AGRICULTURAL TRACTOR", "Other", None),
    ]

    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE {table_name}"))
    await engine.dispose()


async def test_ensure_vehicle_category_backfilled_is_idempotent():
    table_name = _table_name()
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    async with engine.begin() as conn:
        await conn.execute(text(
            f"CREATE TABLE {table_name} (id SERIAL PRIMARY KEY, vehicle_class TEXT NOT NULL, "
            f"vehicle_category TEXT, commercial_tier TEXT)"
        ))
        await conn.execute(text(f"INSERT INTO {table_name} (vehicle_class) VALUES ('MOTOR CAR')"))

    await ensure_vehicle_category_backfilled(engine, table_name=table_name)
    await ensure_vehicle_category_backfilled(engine, table_name=table_name)  # must not raise or reclassify

    async with engine.connect() as conn:
        row = (await conn.execute(text(
            f"SELECT vehicle_category FROM {table_name} WHERE vehicle_class = 'MOTOR CAR'"
        ))).scalar()
    assert row == "Four-Wheeler"

    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE {table_name}"))
    await engine.dispose()
