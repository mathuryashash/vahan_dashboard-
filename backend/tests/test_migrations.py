import os
from uuid import uuid4

import pytest
from sqlalchemy import Column, Index, Integer, MetaData, String, Table, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.core.migrations import (
    drop_orphaned_indexes, ensure_analyzed, ensure_columns, ensure_indexes,
    ensure_no_duplicate_rows, ensure_vehicle_category_backfilled, vacuum_tables,
)

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


async def test_ensure_no_duplicate_rows_removes_duplicates_keeps_highest_id():
    table_name = _table_name()
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    async with engine.begin() as conn:
        await conn.execute(text(
            f"CREATE TABLE {table_name} (id SERIAL PRIMARY KEY, rto_code TEXT, year INT, maker TEXT)"
        ))
        # Two duplicate pairs (same rto_code/year/maker) and one unique row.
        await conn.execute(text(
            f"INSERT INTO {table_name} (rto_code, year, maker) VALUES "
            f"('DL1', 2026, 'HONDA'), ('DL1', 2026, 'HONDA'), "
            f"('UP1', 2026, 'TVS'), ('UP1', 2026, 'TVS'), "
            f"('DL1', 2026, 'TVS')"
        ))

    await ensure_no_duplicate_rows(engine, table_name, ["rto_code", "year", "maker"])

    async with engine.connect() as conn:
        rows = (await conn.execute(text(f"SELECT rto_code, maker FROM {table_name} ORDER BY rto_code, maker"))).all()
    assert rows == [("DL1", "HONDA"), ("DL1", "TVS"), ("UP1", "TVS")]

    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE {table_name}"))
    await engine.dispose()


async def test_ensure_no_duplicate_rows_is_idempotent():
    table_name = _table_name()
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE TABLE {table_name} (id SERIAL PRIMARY KEY, rto_code TEXT, year INT)"))
        await conn.execute(text(f"INSERT INTO {table_name} (rto_code, year) VALUES ('DL1', 2026)"))

    await ensure_no_duplicate_rows(engine, table_name, ["rto_code", "year"])
    await ensure_no_duplicate_rows(engine, table_name, ["rto_code", "year"])  # must not raise or delete the survivor

    async with engine.connect() as conn:
        count = (await conn.execute(text(f"SELECT count(*) FROM {table_name}"))).scalar()
    assert count == 1

    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE {table_name}"))
    await engine.dispose()


async def test_ensure_no_duplicate_rows_handles_null_key_columns():
    # registrations.maker/fuel_type are NULL for 2 of its 3 scrape dimensions
    # -- plain `=` never matches NULL against NULL, so a naive self-join
    # would silently fail to dedupe exactly these rows. Regression test for
    # that NULL-unsafe join bug.
    table_name = _table_name()
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    async with engine.begin() as conn:
        await conn.execute(text(
            f"CREATE TABLE {table_name} (id SERIAL PRIMARY KEY, rto_code TEXT, year INT, maker TEXT)"
        ))
        # Two exact duplicates with maker NULL, plus one unrelated non-NULL row.
        await conn.execute(text(
            f"INSERT INTO {table_name} (rto_code, year, maker) VALUES "
            f"('DL1', 2026, NULL), ('DL1', 2026, NULL), ('DL1', 2026, 'HONDA')"
        ))

    await ensure_no_duplicate_rows(engine, table_name, ["rto_code", "year", "maker"])

    async with engine.connect() as conn:
        rows = (await conn.execute(text(f"SELECT rto_code, maker FROM {table_name} ORDER BY maker NULLS FIRST"))).all()
    assert rows == [("DL1", None), ("DL1", "HONDA")]

    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE {table_name}"))
    await engine.dispose()


async def test_ensure_no_duplicate_rows_skips_the_scan_once_the_unique_index_exists():
    # Once a unique index on exactly `key_columns` exists, the DB itself
    # already guarantees no duplicate can exist -- re-scanning the whole
    # table on every startup to re-confirm that is pure overhead (confirmed
    # live: ~3 minutes on registrations' 26M rows). This must short-circuit
    # instead of running the GROUP BY at all.
    table_name = _table_name()
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    async with engine.begin() as conn:
        await conn.execute(text(
            f"CREATE TABLE {table_name} (id SERIAL PRIMARY KEY, rto_code TEXT, year INT)"
        ))
        await conn.execute(text(f"INSERT INTO {table_name} (rto_code, year) VALUES ('DL1', 2026)"))
        await conn.execute(text(
            f"CREATE UNIQUE INDEX {table_name}_natural_key ON {table_name} (rto_code, year)"
        ))

    original_execute = AsyncConnection.execute
    saw_group_by = False

    async def spying_execute(self, statement, *args, **kwargs):
        nonlocal saw_group_by
        if "GROUP BY" in str(statement):
            saw_group_by = True
        return await original_execute(self, statement, *args, **kwargs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(AsyncConnection, "execute", spying_execute)
        await ensure_no_duplicate_rows(
            engine, table_name, ["rto_code", "year"], unique_index_name=f"{table_name}_natural_key",
        )

    assert not saw_group_by, "should have returned early instead of running the dedup query"

    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE {table_name}"))
    await engine.dispose()


async def test_ensure_bigint_id_widens_integer_column_and_is_idempotent():
    from app.core.migrations import ensure_bigint_id

    table_name = _table_name()
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE TABLE {table_name} (id INTEGER PRIMARY KEY, val TEXT)"))

    await ensure_bigint_id(engine, table_name)
    async with engine.connect() as conn:
        col_type = (await conn.execute(text(
            "SELECT data_type FROM information_schema.columns WHERE table_name = :t AND column_name = 'id'"
        ), {"t": table_name})).scalar()
    assert col_type == "bigint"

    await ensure_bigint_id(engine, table_name)  # idempotent -- must not raise on an already-bigint column

    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE {table_name}"))
    await engine.dispose()


async def test_ensure_bigint_id_rejects_invalid_identifier():
    from app.core.migrations import ensure_bigint_id

    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    with pytest.raises(ValueError):
        await ensure_bigint_id(engine, "registrations; DROP TABLE registrations")
    await engine.dispose()


async def test_coalesce_expression_index_rejects_null_key_duplicates():
    # Regression test for the bug this technique fixes: a plain multi-column
    # UNIQUE index never treats two NULLs as conflicting, so
    # Index("...", "rto_code", "maker", unique=True) would accept unlimited
    # duplicate rows wherever maker is NULL (exactly the shape of
    # idx_reg_natural_key/idx_oem_sales_natural_key in models.py). Wrapping
    # the nullable column in COALESCE(...) inside the index, as those two
    # indexes do, must make it a real constraint again.
    from sqlalchemy.exc import IntegrityError

    table_name = _table_name()
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE TABLE {table_name} (id SERIAL PRIMARY KEY, rto_code TEXT, maker TEXT)"))
        await conn.execute(text(
            f"CREATE UNIQUE INDEX {table_name}_key ON {table_name} (rto_code, COALESCE(maker, ''))"
        ))
        await conn.execute(text(f"INSERT INTO {table_name} (rto_code, maker) VALUES ('DL1', NULL)"))

    # A failed statement aborts its own transaction at the DB level -- each
    # attempt needs its own engine.begin() rather than continuing to use a
    # connection whose transaction already failed.
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(text(f"INSERT INTO {table_name} (rto_code, maker) VALUES ('DL1', NULL)"))

    # A genuinely different row (different rto_code) must still be allowed.
    async with engine.begin() as conn:
        await conn.execute(text(f"INSERT INTO {table_name} (rto_code, maker) VALUES ('UP1', NULL)"))

    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE {table_name}"))
    await engine.dispose()


async def test_ensure_no_duplicate_rows_rejects_invalid_identifiers():
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    with pytest.raises(ValueError):
        await ensure_no_duplicate_rows(engine, "registrations; DROP TABLE registrations", ["year"])
    with pytest.raises(ValueError):
        await ensure_no_duplicate_rows(engine, "registrations", ["year; DROP TABLE registrations"])
    await engine.dispose()


async def test_drop_orphaned_indexes_removes_index_and_is_idempotent():
    table_name = _table_name()
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    index_name = f"ix_{table_name}_state_code"
    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE TABLE {table_name} (id SERIAL PRIMARY KEY, state_code TEXT)"))
        await conn.execute(text(f"CREATE INDEX {index_name} ON {table_name} (state_code)"))

    await drop_orphaned_indexes(engine, [index_name])
    await drop_orphaned_indexes(engine, [index_name])  # idempotent -- must not raise once already gone

    async with engine.connect() as conn:
        indexnames = await conn.run_sync(lambda sync_conn: {i["name"] for i in inspect(sync_conn).get_indexes(table_name)})
    assert index_name not in indexnames

    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE {table_name}"))
    await engine.dispose()


async def test_drop_orphaned_indexes_rejects_invalid_identifier():
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    with pytest.raises(ValueError):
        await drop_orphaned_indexes(engine, ["ix_foo; DROP TABLE registrations"])
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


async def test_vacuum_tables_actually_runs_vacuum():
    # n_dead_tup is refreshed by Postgres's async stats collector, not
    # synchronously after a DELETE in this same test process -- not a
    # reliable signal to assert on here. last_vacuum/last_analyze, by
    # contrast, are set directly by VACUUM/ANALYZE themselves as part of
    # their own execution, so they're the deterministic thing to check.
    table_name = _table_name()
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE TABLE {table_name} (id SERIAL PRIMARY KEY, val TEXT)"))
        await conn.execute(text(f"INSERT INTO {table_name} (val) SELECT 'x' FROM generate_series(1, 100)"))
        await conn.execute(text(f"DELETE FROM {table_name} WHERE id <= 50"))

    async with engine.connect() as conn:
        last_vacuum_before = (await conn.execute(text(
            "SELECT last_vacuum FROM pg_stat_user_tables WHERE relname = :t"
        ), {"t": table_name})).scalar()
    assert last_vacuum_before is None  # never vacuumed yet

    await vacuum_tables(engine, [table_name])

    async with engine.connect() as conn:
        row = (await conn.execute(text(
            "SELECT last_vacuum, last_analyze FROM pg_stat_user_tables WHERE relname = :t"
        ), {"t": table_name})).one()
    assert row.last_vacuum is not None
    assert row.last_analyze is not None

    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE {table_name}"))
    await engine.dispose()


async def test_vacuum_tables_rejects_invalid_identifier():
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    with pytest.raises(ValueError):
        await vacuum_tables(engine, ["registrations; DROP TABLE registrations"])
    await engine.dispose()
    await engine.dispose()
