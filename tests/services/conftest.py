"""Database fixtures — scoped to the service suite only.

These live here, not in tests/conftest.py, so that `pytest tests/domain` runs
with nothing but pytest installed. Domain tests must never need infrastructure;
if importing them starts requiring a driver, the boundary has leaked.
"""

import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import Base

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engine():
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not set — skipping database tests")

    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def session(engine) -> AsyncSession:
    """A session inside a transaction that is rolled back after each test.

    Tests never see each other's rows; the schema is created once per session.
    """
    async with engine.connect() as conn:
        transaction = await conn.begin()
        factory = async_sessionmaker(bind=conn, class_=AsyncSession, expire_on_commit=False)

        async with factory() as session:
            yield session

        await transaction.rollback()
