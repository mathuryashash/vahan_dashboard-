import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool
from app.core.config import settings

logger = logging.getLogger("database")

is_sqlite = settings.DATABASE_URL.startswith("sqlite")

if is_sqlite:
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        future=True,
        poolclass=NullPool,
    )
else:
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        future=True,
        pool_pre_ping=True,
        # Several summary/category endpoints aggregate over the full
        # Registration table and can take single-digit seconds each; the
        # Overview page alone fires ~8 of them on one load. At pool_size=10 +
        # max_overflow=20, that was enough to exhaust the pool under normal
        # use and 500 every request for 30s at a time (confirmed live: a
        # QueuePool TimeoutError storm). The real fix is making those queries
        # fast (see the VACUUM ANALYZE note in that incident, and
        # /summary/available-years' caching) -- this is headroom on top of
        # that, not a replacement for it.
        pool_size=20,
        max_overflow=40,
    )
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    # Import models to register them with Base.metadata
    from app.models import models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    from app.core.migrations import (
        drop_orphaned_indexes, ensure_analyzed, ensure_bigint_id, ensure_columns, ensure_foreign_key,
        ensure_indexes, ensure_no_duplicate_rows, ensure_rtos_backfilled, ensure_vehicle_category_backfilled,
    )
    await ensure_columns(engine, {
        "states": {"zone_code": "VARCHAR(10)"},
        "registrations": {
            "is_supplementary": "BOOLEAN DEFAULT FALSE",
            "vehicle_category": "VARCHAR(20)",
            "commercial_tier": "VARCHAR(15)",
        },
        "users": {"organization_id": "INTEGER"},
    })
    # The 4 tables that actually grow at scale (millions of rows, burning
    # ids on every delete-then-insert rewrite, not just net growth) -- see
    # Registration.id's comment in models.py. The small reference/lookup
    # tables (states, rtos, users, ...) stay Integer; there's no realistic
    # path to 2.1B rows for any of them.
    for table in ["registrations", "maker_category_totals", "fuel_category_totals", "maker_fuel_totals"]:
        await ensure_bigint_id(engine, table)
    # Made redundant by a wider index covering the same leading columns, or
    # found to have zero query-side use -- see the removed Index() calls'
    # git history / the comments left in their place in models.py.
    await drop_orphaned_indexes(engine, [
        "ix_registrations_day", "ix_registrations_recorded_at",
        "idx_mct_year_maker", "idx_mft_year_maker",
    ])
    # Must run before ensure_indexes: the unique indexes declared below on
    # each crosstab table's natural key fail outright if duplicate rows
    # already exist (confirmed live: 31,620 of them on
    # maker_category_totals, silently double-counted into every SUM(count)
    # that read them -- see ensure_no_duplicate_rows' own docstring).
    await ensure_no_duplicate_rows(
        engine, "maker_category_totals", ["rto_code", "year", "maker", "vehicle_class"],
        unique_index_name="idx_mct_natural_key",
    )
    await ensure_no_duplicate_rows(
        engine, "fuel_category_totals", ["rto_code", "year", "fuel_type", "vehicle_class"],
        unique_index_name="idx_fct_natural_key",
    )
    await ensure_no_duplicate_rows(
        engine, "maker_fuel_totals", ["rto_code", "year", "maker", "fuel_type"],
        unique_index_name="idx_mft_natural_key",
    )
    await ensure_no_duplicate_rows(
        engine, "registrations",
        ["rto_code", "year", "month", "is_supplementary", "vehicle_class", "maker", "fuel_type"],
        unique_index_name="idx_reg_natural_key",
    )
    await ensure_no_duplicate_rows(
        engine, "oem_monthly_sales", ["source", "year", "month", "category", "maker"],
        unique_index_name="idx_oem_sales_natural_key",
    )
    await ensure_indexes(engine, Base.metadata)
    await ensure_vehicle_category_backfilled(engine)
    # Must run before any rto_code FK below -- backfills rto_codes seen in
    # scraped registrations but missing from the rtos master table (see that
    # function's docstring for the naming-format history behind this).
    await ensure_rtos_backfilled(engine)
    await ensure_foreign_key(engine, "states", "zone_code", "zones", "zone_code")
    await ensure_foreign_key(engine, "rtos", "state_code", "states", "state_code")
    await ensure_foreign_key(engine, "districts", "state_code", "states", "state_code")
    await ensure_foreign_key(engine, "rto_districts", "rto_code", "rtos", "rto_code")
    await ensure_foreign_key(engine, "rto_districts", "district_code", "districts", "district_code")
    await ensure_foreign_key(engine, "registrations", "state_code", "states", "state_code")
    await ensure_foreign_key(engine, "registrations", "rto_code", "rtos", "rto_code")
    for table in ["maker_category_totals", "fuel_category_totals", "maker_fuel_totals"]:
        await ensure_foreign_key(engine, table, "state_code", "states", "state_code")
        await ensure_foreign_key(engine, table, "rto_code", "rtos", "rto_code")
    await ensure_foreign_key(engine, "users", "scope_state_code", "states", "state_code")
    await ensure_foreign_key(engine, "users", "scope_rto_code", "rtos", "rto_code")
    await ensure_foreign_key(engine, "users", "organization_id", "organizations", "id")
    await ensure_analyzed(engine, list(Base.metadata.tables))
