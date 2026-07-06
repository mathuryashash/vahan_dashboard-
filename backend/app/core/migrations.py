from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def ensure_columns(engine: AsyncEngine, table_columns: dict[str, dict[str, str]]) -> None:
    """Add missing columns to existing tables. SQLite-only ALTER TABLE ADD COLUMN,
    since this project has no migration tool (Alembic) and init_db()'s create_all()
    only creates tables that don't exist yet -- it never alters existing ones."""
    async with engine.begin() as conn:
        for table_name, columns in table_columns.items():
            result = await conn.execute(text(f"PRAGMA table_info({table_name})"))
            existing = {row[1] for row in result.fetchall()}
            for column_name, column_type in columns.items():
                if column_name not in existing:
                    await conn.execute(
                        text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
                    )
