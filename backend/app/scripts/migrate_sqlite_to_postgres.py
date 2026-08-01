"""Copy the existing SQLite dashboard data into PostgreSQL in resumable batches.

Run this only after taking a backup of the SQLite source file. It never changes
the source. The target must be empty unless --replace is explicitly supplied.
"""

import argparse
import asyncio
import sqlite3
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import Boolean, Date, DateTime, func, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.database import Base
from app.models import models  # noqa: F401 - register ORM tables on Base.metadata

BATCH_SIZE = 10_000
TABLE_ORDER = (
    "zones",
    "states",
    "districts",
    "rtos",
    "rto_districts",
    "registrations",
    "dashboard_summary",
    "oem_monthly_sales",
)


def _coerce(value, column):
    if value is None:
        return None
    if isinstance(column.type, Boolean):
        return bool(value)
    if isinstance(column.type, DateTime) and isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    if isinstance(column.type, Date) and isinstance(value, str):
        return date.fromisoformat(value)
    return value


def _source_tables(source: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in source.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


async def _target_has_data(engine) -> bool:
    async with engine.connect() as connection:
        for table_name in TABLE_ORDER:
            table = Base.metadata.tables[table_name]
            if (await connection.execute(select(func.count()).select_from(table))).scalar_one():
                return True
    return False


async def _copy_table(source: sqlite3.Connection, engine, table_name: str) -> int:
    table = Base.metadata.tables[table_name]
    source_columns = {
        row[1] for row in source.execute(f"PRAGMA table_info({table_name})")
    }
    columns = [column for column in table.columns if column.name in source_columns]
    if not columns:
        return 0

    names = ", ".join(column.name for column in columns)
    column_names = [column.name for column in columns]
    cursor = source.execute(f"SELECT {names} FROM {table_name}")
    copied = 0
    while rows := cursor.fetchmany(BATCH_SIZE):
        payload = [
            tuple(_coerce(row[column.name], column) for column in columns)
            for row in rows
        ]
        async with engine.begin() as target:
            raw_connection = await target.get_raw_connection()
            await raw_connection.driver_connection.copy_records_to_table(
                table_name,
                records=payload,
                columns=column_names,
            )
        copied += len(payload)
        if copied % 100_000 == 0 or len(rows) < BATCH_SIZE:
            print(f"{table_name}: {copied:,} rows copied", flush=True)
    return copied


async def _reset_sequences(engine) -> None:
    async with engine.begin() as connection:
        for table_name in TABLE_ORDER:
            table = Base.metadata.tables[table_name]
            if "id" not in table.c:
                continue
            await connection.execute(
                text(
                    "SELECT setval(pg_get_serial_sequence(:table_name, 'id'), "
                    "COALESCE((SELECT MAX(id) FROM " + table_name + "), 1), true)"
                ),
                {"table_name": table_name},
            )


async def _drop_secondary_indexes(engine) -> None:
    async with engine.begin() as connection:
        for table_name in TABLE_ORDER:
            table = Base.metadata.tables[table_name]
            for index in table.indexes:
                await connection.run_sync(lambda sync_connection, index=index: index.drop(sync_connection, checkfirst=True))


async def _create_secondary_indexes(engine) -> None:
    async with engine.begin() as connection:
        for table_name in TABLE_ORDER:
            table = Base.metadata.tables[table_name]
            for index in table.indexes:
                await connection.run_sync(lambda sync_connection, index=index: index.create(sync_connection, checkfirst=True))


async def _analyze(engine) -> None:
    """A bulk COPY leaves the planner's row-count/statistics estimates at
    whatever they were before the load (0 for a fresh table) until something
    runs ANALYZE -- autovacuum's autoanalyze eventually catches up on its own
    schedule, but until then every query plans against a table it thinks is
    empty. Measured impact on this data: KPI/trend/category queries ran
    5-8x slower before an explicit ANALYZE than after."""
    async with engine.begin() as connection:
        for table_name in TABLE_ORDER:
            await connection.execute(text(f"ANALYZE {table_name}"))


async def migrate(source_path: Path, replace: bool) -> None:
    if not source_path.is_file():
        raise FileNotFoundError(source_path)

    source = sqlite3.connect(source_path)
    source.row_factory = sqlite3.Row
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            if replace:
                for table_name in reversed(TABLE_ORDER):
                    await connection.execute(text(f"TRUNCATE TABLE {table_name} RESTART IDENTITY CASCADE"))
        if not replace and await _target_has_data(engine):
            raise RuntimeError("Target PostgreSQL database contains data. Re-run with --replace to overwrite it.")

        await _drop_secondary_indexes(engine)
        available = _source_tables(source)
        for table_name in TABLE_ORDER:
            if table_name in available:
                copied = await _copy_table(source, engine, table_name)
                source_count = source.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
                if copied != source_count:
                    raise RuntimeError(f"{table_name}: copied {copied}, expected {source_count}")
        await _reset_sequences(engine)
        await _create_secondary_indexes(engine)
        await _analyze(engine)
        print("SQLite to PostgreSQL migration completed successfully.")
    finally:
        source.close()
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Path to the SQLite vahan.db source")
    parser.add_argument("--replace", action="store_true", help="Explicitly clear the PostgreSQL target before importing")
    arguments = parser.parse_args()
    asyncio.run(migrate(arguments.source, arguments.replace))
