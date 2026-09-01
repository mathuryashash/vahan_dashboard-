import os

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.database import Base
import app.models.models  # noqa: F401 - ensures models are registered on Base.metadata
from app.core.auth import get_current_user
from app.main import app
from app.core.database import get_db
from app.models.models import User, UserRole

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://vahan:vahan@127.0.0.1:5432/vahan_test",
)


@pytest.fixture
async def db_session():
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def client(db_session):
    from httpx import AsyncClient, ASGITransport

    async def override_get_db():
        yield db_session

    # Auth defaults to a stub admin: most tests exercise dashboard/data
    # behavior, not the access-hierarchy system itself, and shouldn't need
    # to carry a login step just to reach an admin-gated endpoint. Tests for
    # the auth system itself (login, role enforcement) override this back
    # via app.dependency_overrides directly -- see test_auth.py.
    async def override_get_current_user():
        return User(id=0, email="test-admin@example.com", role=UserRole.ADMIN, is_active=True)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
