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
    from app.core.migrations import ensure_analyzed, ensure_columns, ensure_indexes, ensure_vehicle_category_backfilled
    await ensure_columns(engine, {
        "states": {"zone_code": "VARCHAR(10)"},
        "registrations": {
            "is_supplementary": "BOOLEAN DEFAULT FALSE",
            "vehicle_category": "VARCHAR(20)",
            "commercial_tier": "VARCHAR(15)",
        },
    })
    await ensure_indexes(engine, Base.metadata)
    await ensure_vehicle_category_backfilled(engine)
    await ensure_analyzed(engine, list(Base.metadata.tables))
