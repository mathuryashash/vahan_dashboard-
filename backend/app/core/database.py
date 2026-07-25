import logging

import aiosqlite
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.core.config import settings

logger = logging.getLogger("database")

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_concurrency_pragmas(dbapi_connection, _connection_record):
    """Every scraper dimension (maker/vehicle_class/fuel) now runs as its own
    OS process writing to this same SQLite file concurrently (see
    scraper_service.run_scraper). Plain SQLite defaults to a 0ms busy_timeout
    (an instant "database is locked" the moment two writers overlap, as
    happened when a manual CLI scrape collided with an API-triggered one) and
    rollback-journal mode, which holds an exclusive lock for a writer's whole
    transaction. WAL lets readers proceed during a write and only serializes
    the brief per-commit window; busy_timeout makes a second writer wait for
    that window instead of failing immediately.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()

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


async def checkpoint_wal() -> None:
    """Force the WAL back into the main db file. SQLite's default
    auto-checkpoint is passive -- it silently skips whenever any other
    connection has an open read, which the API server always has some of
    while a scrape runs. Without an explicit checkpoint the WAL just grows
    for the scrape's whole duration (observed 547MB after one run), and
    every read degrades badly until it's flushed -- SQLite has to check WAL
    frames for any page it touches, not just the ones actually changed.
    Called right after a scrape finishes instead of hoping auto-checkpoint
    gets a clear window."""
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
        busy, log_frames, checkpointed = result.fetchone()
        if busy:
            logger.warning(
                "WAL checkpoint incomplete (blocked by another connection): %d/%d frames flushed",
                checkpointed, log_frames,
            )
        else:
            logger.info("WAL checkpoint complete: %d frames flushed", checkpointed)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    from app.core.migrations import ensure_columns
    await ensure_columns(engine, {
        "states": {"zone_code": "VARCHAR(10)"},
        "registrations": {"is_supplementary": "BOOLEAN DEFAULT 0"},
    })
