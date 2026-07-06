import re

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


async def ensure_columns(engine: AsyncEngine, table_columns: dict[str, dict[str, str]]) -> None:
    """Add missing columns to existing tables. SQLite-only ALTER TABLE ADD COLUMN,
    since this project has no migration tool (Alembic) and init_db()'s create_all()
    only creates tables that don't exist yet -- it never alters existing ones.

    table_name and column_name are validated as plain SQL identifiers before being
    interpolated into raw SQL. column_type is NOT validated the same way -- it's a
    trusted/internal SQL type expression (e.g. "VARCHAR(10)"), not an identifier, and
    callers must not pass untrusted input for it.
    """
    async with engine.begin() as conn:
        for table_name, columns in table_columns.items():
            if not _IDENTIFIER_RE.match(table_name):
                raise ValueError(f"Invalid table name: {table_name!r}")
            result = await conn.execute(text(f"PRAGMA table_info({table_name})"))
            existing = {row[1] for row in result.fetchall()}
            for column_name, column_type in columns.items():
                if not _IDENTIFIER_RE.match(column_name):
                    raise ValueError(f"Invalid column name: {column_name!r}")
                if column_name not in existing:
                    try:
                        await conn.execute(
                            text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
                        )
                    except OperationalError as exc:
                        # Tolerate a race between concurrent workers that both see the
                        # column missing and both try to add it -- only the loser's
                        # "duplicate column" error is expected/harmless here.
                        if "duplicate column" not in str(exc).lower():
                            raise
