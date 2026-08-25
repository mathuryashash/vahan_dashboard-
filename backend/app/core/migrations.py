import re

from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.schema import CreateIndex

from app.core.query_filters import _VEHICLE_CATEGORY_MAP

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


async def ensure_indexes(engine: AsyncEngine, metadata) -> None:
    """Create any index declared in `metadata` that doesn't exist yet.

    Base.metadata.create_all() (called earlier in init_db) only emits a
    table's indexes as part of creating that table -- it does nothing for
    indexes missing from a table that already exists. That gap is exactly
    what a docker-entrypoint-initdb.d seed script interrupted mid-run (e.g.
    by a host Docker Desktop crash, observed during manual testing) leaves
    behind: the table and its data land fine, but a CREATE INDEX later in
    the script never ran. CREATE INDEX IF NOT EXISTS makes this idempotent
    and safe to run on every startup, not just once.
    """
    async with engine.begin() as conn:
        for table in metadata.tables.values():
            for index in table.indexes:
                ddl = CreateIndex(index, if_not_exists=True)
                await conn.execute(ddl)


def _sql_literal(value: str) -> str:
    """Single-quoted SQL string literal, with embedded quotes doubled.
    Values here always come from our own hardcoded classification table
    (never user input), but this still avoids a bad literal if a future
    raw value ever contains an apostrophe."""
    return "'" + value.replace("'", "''") + "'"


async def ensure_vehicle_category_backfilled(engine: AsyncEngine, table_name: str = "registrations") -> None:
    """Classify every row with vehicle_category still NULL, in one bulk
    UPDATE using a SQL CASE expression built from classify_vehicle's own
    lookup table -- not a per-row Python loop. A per-row loop here was
    originally tried and measured at ~100 rows/sec against this table (one
    network round trip per row), which projects to over 3 days against
    13M+ existing rows; a single indexed bulk UPDATE does the same work
    server-side in one pass. Idempotent: only ever touches rows where
    vehicle_category IS NULL, so a completed backfill costs one cheap
    no-op UPDATE (matches zero rows) on every subsequent startup.
    """
    if not _IDENTIFIER_RE.match(table_name):
        raise ValueError(f"Invalid table name: {table_name!r}")

    category_cases = "\n        ".join(
        f"WHEN {_sql_literal(raw)} THEN {_sql_literal(category)}"
        for raw, (category, _tier) in _VEHICLE_CATEGORY_MAP.items()
    )
    tier_cases = "\n        ".join(
        f"WHEN {_sql_literal(raw)} THEN {_sql_literal(tier)}"
        for raw, (_category, tier) in _VEHICLE_CATEGORY_MAP.items()
        if tier is not None
    )
    async with engine.begin() as conn:
        await conn.execute(text(f"""
            UPDATE {table_name}
            SET vehicle_category = CASE UPPER(vehicle_class)
                {category_cases}
                ELSE 'Other'
            END,
            commercial_tier = CASE UPPER(vehicle_class)
                {tier_cases}
                ELSE NULL
            END
            WHERE vehicle_category IS NULL
        """))


async def ensure_analyzed(engine: AsyncEngine, table_names: list[str]) -> None:
    """ANALYZE any table whose planner statistics say it's empty when it
    actually has rows.

    A bulk load (COPY, or this same interrupted-seed scenario ensure_indexes
    guards against) leaves pg_class.reltuples -- the row count the query
    planner actually reads when choosing a plan -- at 0 until something runs
    ANALYZE. Measured impact on this data: KPI/trend/category queries ran
    5-8x slower with reltuples=0 than after an explicit ANALYZE.

    Deliberately reads pg_class.reltuples, not pg_stat_user_tables -- the
    latter's last_analyze/n_live_tup are separate monitoring counters that
    pg_stat_reset() clears independently of the real catalog stats, so they
    can misreport "never analyzed" for a table the planner already has
    correct statistics for (confirmed by hand while building this check).
    reltuples is what create_all()/ANALYZE actually write and what the
    planner reads, so it can't drift from what matters like that.

    Note: For SQLite, we just run ANALYZE unconditionally since it's fast.
    """
    is_sqlite = str(engine.url).startswith("sqlite")
    async with engine.connect() as conn:
        for table_name in table_names:
            if not _IDENTIFIER_RE.match(table_name):
                raise ValueError(f"Invalid table name: {table_name!r}")
            
            if is_sqlite:
                # SQLite: just run ANALYZE (fast, no pg_class)
                await conn.execute(text(f"ANALYZE {table_name}"))
                await conn.commit()
                continue
                
            reltuples = (
                await conn.execute(
                    text("SELECT reltuples FROM pg_class WHERE relname = :table_name"),
                    {"table_name": table_name},
                )
            ).scalar()
            if reltuples is None or reltuples > 0:
                continue
            has_rows = (
                await conn.execute(text(f"SELECT EXISTS (SELECT 1 FROM {table_name})"))
            ).scalar()
            if has_rows:
                await conn.execute(text(f"ANALYZE {table_name}"))
                await conn.commit()
