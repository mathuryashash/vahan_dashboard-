import re

from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


async def ensure_columns(engine: AsyncEngine, table_columns: dict[str, dict[str, str]]) -> None:
    """Add missing columns to existing tables without coupling to a database dialect.

    table_name and column_name are validated as plain SQL identifiers before being
    interpolated into raw SQL. column_type is NOT validated the same way -- it's a
    trusted/internal SQL type expression (e.g. "VARCHAR(10)"), not an identifier, and
    callers must not pass untrusted input for it.
    """
    async with engine.begin() as conn:
        for table_name, columns in table_columns.items():
            if not _IDENTIFIER_RE.match(table_name):
                raise ValueError(f"Invalid table name: {table_name!r}")
            for column_name in columns:
                if not _IDENTIFIER_RE.match(column_name):
                    raise ValueError(f"Invalid column name: {column_name!r}")
            existing = await conn.run_sync(
                lambda sync_conn: {column["name"] for column in inspect(sync_conn).get_columns(table_name)}
            )
            for column_name, column_type in columns.items():
                if column_name not in existing:
                    try:
                        await conn.execute(
                            text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
                        )
                    except OperationalError as exc:
                        # Tolerate a race between concurrent workers that both see the
                        # column missing and both try to add it.
                        if not any(marker in str(exc).lower() for marker in ("duplicate column", "already exists")):
                            raise
