"""Order lifecycle against a real Postgres.

Unit tests cannot reach any of this: the price snapshot is a column write, the
cart clear and the order insert share one transaction, Numeric(10,2) rounding is
the database's opinion, and the rate limit is a COUNT over created_at.

State is built through the services (category_service.create, product_service.create,
cart_service.add) so a test exercises the same write path production uses. Orders
needed only as filler — the rate-limit and listing tests — are inserted directly:
create_order is the thing under test, not a fixture.
"""

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from config import ORDER_RATE_LIMIT
from db.models import ACTIVE_STATUSES, CartItem, Order, OrderItem, OrderStatus
from services import cart_service, order_service, product_service
from services.order_service import CartNotOrderable, RateLimitExceeded

pytestmark = pytest.mark.asyncio

ADDRESS = "Rue de Test 1"
NAME = "Tester"
PHONE = "+3216000000"


async def _place(session, user_id: int) -> Order:
    return await order_service.create_order(
        session, user_id, address=ADDRESS, contact_name=NAME, contact_phone=PHONE
    )


async def _order_count(session, user_id: int) -> int:
    return (
        await session.execute(select(func.count(Order.id)).where(Order.user_id == user_id))
    ).scalar()


async def _cart_count(session, user_id: int) -> int:
    return (
        await session.execute(select(func.count(CartItem.id)).where(CartItem.user_id == user_id))
    ).scalar()


async def _items(session, order_id: int) -> list[OrderItem]:
    return list(
        (
            await session.execute(
                select(OrderItem).where(OrderItem.order_id == order_id).order_by(OrderItem.id)
            )
        ).scalars()
    )


def _filler(user_id: int) -> Order:
    """A row that only has to exist and be recent — never the object under test."""
    return Order(
        user_id=user_id,
        status=OrderStatus.PENDING,
        total_price=Decimal("1.00"),
        address=ADDRESS,
        contact_name=NAME,
        contact_phone=PHONE,
    )


# ── create_order: the price snapshot ──────────────────────────────────────────


async def test_create_order_snapshots_price_into_order_items(session, user, make_product):
    """order_items.price must not follow later changes to products.price."""
    product = await make_product(price="12.50")
    await cart_service.add(session, user, product.id, 2)

    order = await _place(session, user)
    items = await _items(session, order.id)

    assert len(items) == 1
    assert items[0].price == Decimal("12.50")

    # The menu is repriced after the order was placed.
    await product_service.update_price(session, product.id, Decimal("99.00"))

    session.expunge_all()
    items = await _items(session, order.id)
    assert items[0].price == Decimal("12.50"), "snapshot followed the product price"

    reread = await session.get(Order, order.id)
    assert reread.total_price == Decimal("25.00"), "total followed the product price"


async def test_snapshot_is_decimal_at_two_places(session, user, make_product):
    product = await make_product(price="0.10")
    await cart_service.add(session, user, product.id, 3)

    order = await _place(session, user)

    session.expunge_all()
    items = await _items(session, order.id)
    reread = await session.get(Order, order.id)

    assert isinstance(items[0].price, Decimal)
    assert isinstance(reread.total_price, Decimal)
    # Numeric(10, 2) round-trips with a scale of exactly two.
    assert items[0].price == Decimal("0.10")
    assert items[0].price.as_tuple().exponent == -2
    assert reread.total_price == Decimal("0.30")
    assert reread.total_price.as_tuple().exponent == -2


async def test_total_matches_sum_of_order_items(session, user, make_product):
    cheap = await make_product(price="3.30")
    dear = await make_product(price="14.95")
    await cart_service.add(session, user, cheap.id, 3)
    await cart_service.add(session, user, dear.id, 2)

    order = await _place(session, user)

    session.expunge_all()
    items = await _items(session, order.id)
    reread = await session.get(Order, order.id)

    assert sorted(i.price for i in items) == [Decimal("3.30"), Decimal("14.95")]
    assert sum((i.price * i.quantity for i in items), Decimal("0")) == reread.total_price
    assert reread.total_price == Decimal("39.80")


# ── create_order: the cart ────────────────────────────────────────────────────


async def test_create_order_empties_the_cart(session, user, make_product):
    product = await make_product()
    await cart_service.add(session, user, product.id, 2)
    assert await _cart_count(session, user) == 1

    await _place(session, user)

    assert await _cart_count(session, user) == 0


async def test_create_order_leaves_another_users_cart_alone(
    session, user, other_user, make_product
):
    product = await make_product()
    await cart_service.add(session, user, product.id, 1)
    await cart_service.add(session, other_user, product.id, 1)

    await _place(session, user)

    assert await _cart_count(session, user) == 0
    assert await _cart_count(session, other_user) == 1


async def test_create_order_refuses_an_empty_cart(session, user):
    with pytest.raises(CartNotOrderable) as excinfo:
        await _place(session, user)

    assert excinfo.value.problems == []
    assert await _order_count(session, user) == 0


# ── create_order: a cart that went stale ──────────────────────────────────────


@pytest.mark.parametrize(
    ("qty", "changed", "kind"),
    [
        (1, {"is_deleted": True}, "gone"),
        (1, {"in_stock": False}, "out_of_stock"),
        # The admin lowered the per-order cap under what is already in the cart.
        (5, {"max_quantity": 2}, "over_max"),
    ],
    ids=["deleted", "out_of_stock", "over_max"],
)
async def test_create_order_rejects_a_cart_that_went_stale(
    session, user, make_product, qty, changed, kind
):
    """The cart is validated at order time, not only when it was filled."""
    product = await make_product(max_quantity=10)
    # Filled while the product was still orderable, then the menu changed.
    await cart_service.add(session, user, product.id, qty)
    await product_service.update(session, product.id, **changed)

    with pytest.raises(CartNotOrderable) as excinfo:
        await _place(session, user)

    problems = excinfo.value.problems
    assert [p.kind for p in problems] == [kind]
    assert problems[0].product_id == product.id


async def test_a_rejected_cart_creates_no_order_and_survives(session, user, make_product):
    good = await make_product(price="5.00")
    bad = await make_product(price="5.00")
    await cart_service.add(session, user, good.id, 1)
    await cart_service.add(session, user, bad.id, 1)
    await product_service.update(session, bad.id, is_deleted=True)

    with pytest.raises(CartNotOrderable):
        await _place(session, user)

    assert await _order_count(session, user) == 0
    assert (
        await session.execute(select(func.count(OrderItem.id)))
    ).scalar() == 0
    # Nothing was consumed: the customer fixes the cart and retries.
    assert await _cart_count(session, user) == 2


# ── create_order: the rate limit ──────────────────────────────────────────────


async def test_orders_in_last_hour_counts_only_this_user(session, user, other_user):
    session.add_all([_filler(user), _filler(user), _filler(other_user)])
    await session.commit()

    assert await order_service.orders_in_last_hour(session, user) == 2
    assert await order_service.orders_in_last_hour(session, other_user) == 1


async def test_rate_limit_blocks_the_next_order_in_an_hour(session, user, make_product):
    session.add_all([_filler(user) for _ in range(ORDER_RATE_LIMIT)])
    await session.commit()

    product = await make_product()
    await cart_service.add(session, user, product.id, 1)

    with pytest.raises(RateLimitExceeded) as excinfo:
        await _place(session, user)

    assert excinfo.value.placed == ORDER_RATE_LIMIT
    assert excinfo.value.limit == ORDER_RATE_LIMIT
    assert await _order_count(session, user) == ORDER_RATE_LIMIT
    # The cart is untouched — the customer may retry once the hour rolls over.
    assert await _cart_count(session, user) == 1


async def test_rate_limit_lets_the_last_allowed_order_through(session, user, make_product):
    session.add_all([_filler(user) for _ in range(ORDER_RATE_LIMIT - 1)])
    await session.commit()

    product = await make_product()
    await cart_service.add(session, user, product.id, 1)

    order = await _place(session, user)

    assert order.id is not None
    assert await _order_count(session, user) == ORDER_RATE_LIMIT


# ── settle_payment ────────────────────────────────────────────────────────────


async def test_settle_payment_moves_pending_to_paid(session, user, make_product):
    product = await make_product()
    await cart_service.add(session, user, product.id, 1)
    order = await _place(session, user)

    settled = await order_service.settle_payment(session, order.id, OrderStatus.PAID)

    assert settled is not None
    assert settled.status == OrderStatus.PAID

    session.expunge_all()
    assert (await session.get(Order, order.id)).status == OrderStatus.PAID


async def test_settle_payment_is_idempotent(session, user, make_product):
    """A second tap on the admin buttons must not overwrite the first decision."""
    product = await make_product()
    await cart_service.add(session, user, product.id, 1)
    order = await _place(session, user)

    assert await order_service.settle_payment(session, order.id, OrderStatus.PAID) is not None
    # Reject, arriving after the confirm.
    assert (
        await order_service.settle_payment(session, order.id, OrderStatus.CANCELLED_UNPAID)
        is None
    )

    session.expunge_all()
    assert (await session.get(Order, order.id)).status == OrderStatus.PAID


async def test_settle_payment_ignores_an_unknown_order(session):
    assert await order_service.settle_payment(session, 10**9, OrderStatus.PAID) is None


# ── advance_status ────────────────────────────────────────────────────────────


async def test_advance_status_walks_the_chain(session, user, make_product):
    product = await make_product()
    await cart_service.add(session, user, product.id, 1)
    order = await _place(session, user)

    walked = []
    for _ in range(4):
        advanced = await order_service.advance_status(session, order.id)
        assert advanced is not None
        walked.append(advanced.status)

    assert walked == [
        OrderStatus.PAID,
        OrderStatus.PREPARING,
        OrderStatus.DELIVERING,
        OrderStatus.DELIVERED,
    ]


async def test_advance_status_stops_at_delivered(session, user, make_product):
    product = await make_product()
    await cart_service.add(session, user, product.id, 1)
    order = await _place(session, user)
    await order_service.set_status(session, order.id, OrderStatus.DELIVERED)

    assert await order_service.advance_status(session, order.id) is None

    session.expunge_all()
    assert (await session.get(Order, order.id)).status == OrderStatus.DELIVERED


async def test_advance_status_stops_at_cancelled_unpaid(session, user, make_product):
    product = await make_product()
    await cart_service.add(session, user, product.id, 1)
    order = await _place(session, user)
    await order_service.set_status(session, order.id, OrderStatus.CANCELLED_UNPAID)

    assert await order_service.advance_status(session, order.id) is None

    session.expunge_all()
    assert (await session.get(Order, order.id)).status == OrderStatus.CANCELLED_UNPAID


# ── reads ─────────────────────────────────────────────────────────────────────


async def test_get_for_user_hides_another_customers_order(
    session, user, other_user, make_product
):
    """IDOR guard: a guessed id must be indistinguishable from a missing one."""
    product = await make_product()
    await cart_service.add(session, user, product.id, 1)
    order = await _place(session, user)

    assert await order_service.get_for_user(session, order.id, other_user) is None
    assert await order_service.get_for_user(session, 10**9, user) is None


async def test_get_for_user_returns_own_order_with_items_loaded(session, user, make_product):
    product = await make_product(price="7.25")
    await cart_service.add(session, user, product.id, 2)
    order = await _place(session, user)

    session.expunge_all()
    found = await order_service.get_for_user(session, order.id, user)

    assert found is not None
    # Eager-loaded: reaching items/product off an async session would otherwise raise.
    assert [(i.product.name, i.quantity, i.price) for i in found.items] == [
        (product.name, 2, Decimal("7.25"))
    ]


async def test_list_for_user_returns_only_that_users_orders(session, user, other_user):
    mine = _filler(user)
    theirs = _filler(other_user)
    session.add_all([mine, theirs])
    await session.commit()

    ids = [o.id for o in await order_service.list_for_user(session, user)]

    assert mine.id in ids
    assert theirs.id not in ids


async def test_list_active_skips_terminal_statuses(session, user):
    pending = _filler(user)
    delivered = _filler(user)
    cancelled = _filler(user)
    session.add_all([pending, delivered, cancelled])
    await session.commit()
    await order_service.set_status(session, delivered.id, OrderStatus.DELIVERED)
    await order_service.set_status(session, cancelled.id, OrderStatus.CANCELLED_UNPAID)

    active = await order_service.list_active(session)
    ids = [o.id for o in active]

    assert pending.id in ids
    assert delivered.id not in ids
    assert cancelled.id not in ids
    assert all(o.status in ACTIVE_STATUSES for o in active)


async def test_list_recent_includes_every_status(session, user):
    pending = _filler(user)
    delivered = _filler(user)
    session.add_all([pending, delivered])
    await session.commit()
    await order_service.set_status(session, delivered.id, OrderStatus.DELIVERED)

    ids = [o.id for o in await order_service.list_recent(session, limit=50)]

    assert pending.id in ids
    assert delivered.id in ids
