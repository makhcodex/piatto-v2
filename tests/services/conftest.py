"""Database fixtures — scoped to the service suite only.

These live here, not in tests/conftest.py, so that `pytest tests/domain` runs
with nothing but pytest installed. Domain tests must never need infrastructure;
if importing them starts requiring a driver, the boundary has leaked.

Every await below happens in the event loop of the test being run — pyproject pins
the fixture loop scope to "function" for exactly that reason. An asyncpg connection
driven from two loops fails with "another operation is in progress". The engine
fixture is therefore synchronous (create_async_engine needs no loop) and can stay
session-scoped, while the connection is opened per test.
"""

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from itertools import count

import pytest
import pytest_asyncio
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from db.models import Base, Category, Order, OrderStatus, Product
from services import category_service, product_service, sweep, user_service

# The URL usually lives in .env next to DATABASE_URL; config.py is not imported
# here, so nothing else would load it.
load_dotenv()

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "")

# Unique per process: products.name carries uq_products_name, so a hardcoded name
# would collide with a row left by an earlier test.
_serial = count(1)

_schema_ready = False


@pytest.fixture(scope="session")
def engine():
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not set — skipping database tests")

    # NullPool: a connection is never recycled into another test, so a test that
    # ends badly cannot hand the next one a connection with a transaction open.
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    yield engine
    engine.sync_engine.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncSession:
    """A session inside a transaction that is rolled back after each test.

    Services commit; those commits land in a SAVEPOINT inside the outer transaction
    (SQLAlchemy's default join_transaction_mode), so the rollback below still wipes
    everything the test wrote. Tests never see each other's rows.

    expire_on_commit=False mirrors db/engine.py: services read attributes off an
    object after their own commit, and an expired instance would re-query.
    """
    global _schema_ready

    async with engine.connect() as conn:
        if not _schema_ready:
            # The test database is migrated with `alembic upgrade head`; this only
            # covers a database that has not been, and never drops anything.
            await conn.run_sync(Base.metadata.create_all)
            await conn.commit()
            _schema_ready = True

        transaction = await conn.begin()
        factory = async_sessionmaker(bind=conn, class_=AsyncSession, expire_on_commit=False)

        async with factory() as session:
            yield session

        await transaction.rollback()


# ── State builders ────────────────────────────────────────────────────────────
#
# Built through the services where a service exists, so a test exercises the same
# write path production uses.


@pytest_asyncio.fixture
async def user(session) -> int:
    """users.id — the internal PK every service takes, not a telegram_id."""
    return await user_service.get_or_create(session, telegram_id=next(_serial) + 10_000_000)


@pytest_asyncio.fixture
async def other_user(session) -> int:
    return await user_service.get_or_create(session, telegram_id=next(_serial) + 20_000_000)


@pytest_asyncio.fixture
async def category(session) -> Category:
    serial = next(_serial)
    return await category_service.create(session, slug=f"cat{serial}", name=f"Category {serial}")


@pytest.fixture
def make_product(session, category):
    """Factory: a product in the shared category, with a name unique per call."""

    async def _make(
        price: str = "10.00",
        max_quantity: int = 10,
        in_stock: bool = True,
        is_deleted: bool = False,
    ) -> Product:
        serial = next(_serial)
        product = await product_service.create(
            session,
            category_id=category.id,
            name=f"Product {serial}",
            price=Decimal(price),
            max_quantity=max_quantity,
        )
        if not in_stock or is_deleted:
            # Straight through update(): create() takes neither flag.
            await product_service.update(
                session, product.id, in_stock=in_stock, is_deleted=is_deleted
            )
        return product

    return _make


@pytest.fixture
def make_order(session):
    """Factory for an order with a chosen age and status.

    Inserted straight through the ORM: the sweep only ever reads status, created_at
    and warning_sent, and going through create_order would drag in a cart, a rate
    limit, and a price snapshot that no sweep test cares about. created_at is passed
    explicitly (timezone-aware UTC) instead of leaning on the server default — the
    whole point is to place the row on either side of a time window.
    """

    async def _make(
        user_id: int,
        *,
        minutes_ago: float = 0,
        status: OrderStatus = OrderStatus.PENDING,
        warning_sent: bool = False,
    ) -> Order:
        order = Order(
            user_id=user_id,
            status=status,
            total_price=Decimal("10.00"),
            address="Rue de Test 1",
            contact_name="Tester",
            contact_phone="+3216000000",
            created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
            warning_sent=warning_sent,
        )
        session.add(order)
        await session.commit()
        return order

    return _make


class FakeBot:
    """Stands in for aiogram's Bot. The database stays real; Telegram never does."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))

    def to(self, chat_id: int) -> list[str]:
        return [text for target, text in self.sent if target == chat_id]


class FailingBot(FakeBot):
    """Every send raises — the Telegram outage case.

    sweep._notify swallows it; these tests assert the commit that came first survived.
    """

    async def send_message(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))
        raise RuntimeError("telegram is down")


@pytest.fixture
def bot() -> FakeBot:
    return FakeBot()


@pytest.fixture
def failing_bot() -> FailingBot:
    return FailingBot()


@pytest.fixture
def sweep_session(monkeypatch, session):
    """Point sweep.run_once at the test's session instead of a real engine.

    run_once opens its own session through get_session_factory() — it takes no
    session argument — so without this it would connect to DATABASE_URL and see
    none of the rows this test wrote inside its rolled-back transaction. The
    database is still the real piatto_test; only the way the sweep reaches it is
    redirected, and __aexit__ deliberately leaves the session open for assertions.
    """

    class _Handle:
        async def __aenter__(self) -> AsyncSession:
            return session

        async def __aexit__(self, *exc_info) -> bool:
            return False

    monkeypatch.setattr(sweep, "get_session_factory", lambda: _Handle)
    return session


@pytest.fixture
def make_user(session):
    """Factory for tests that need more than the two named user fixtures."""

    async def _make() -> int:
        return await user_service.get_or_create(session, telegram_id=next(_serial) + 30_000_000)

    return _make
