"""Cart persistence against a real Postgres.

Unit tests cannot reach these: the UNIQUE(user_id, product_id) constraint,
Numeric(10,2) round-tripping, and cascade deletes are database behaviour.

domain/ already owns the rules and is tested without a database; what is checked
here is that the service persists what the rules decided — one row per product,
quantities added rather than assigned, and no price anywhere in cart_items.
"""

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from db.models import CartItem, User
from domain import pricing
from services import cart_service, product_service

pytestmark = pytest.mark.asyncio


async def _rows(session, user_id: int) -> list[CartItem]:
    return list(
        (
            await session.execute(
                select(CartItem).where(CartItem.user_id == user_id).order_by(CartItem.id)
            )
        ).scalars()
    )


async def _row_count(session, user_id: int) -> int:
    return (
        await session.execute(select(func.count(CartItem.id)).where(CartItem.user_id == user_id))
    ).scalar()


# ── add: the addition invariant ───────────────────────────────────────────────


async def test_add_creates_row(session, user, make_product):
    product = await make_product()

    added, problem = await cart_service.add(session, user, product.id, 2)

    assert (added, problem) == (2, None)
    rows = await _rows(session, user)
    assert [(r.product_id, r.qty) for r in rows] == [(product.id, 2)]


async def test_add_accumulates_instead_of_overwriting(session, user, make_product):
    """The regression guard for v1 bug #6, at the persistence level."""
    product = await make_product(max_quantity=10)

    await cart_service.add(session, user, product.id, 2)
    added, problem = await cart_service.add(session, user, product.id, 3)

    assert (added, problem) == (3, None)
    rows = await _rows(session, user)
    assert len(rows) == 1, "a second add must not create a second row"
    assert rows[0].qty == 5, "quantity was assigned instead of added"


async def test_add_is_capped_at_max_quantity(session, user, make_product):
    product = await make_product(max_quantity=3)

    added, problem = await cart_service.add(session, user, product.id, 5)

    # allowed_to_add clamps to the room left; the clamp itself is not a problem.
    assert added == 3
    assert problem is None
    assert (await _rows(session, user))[0].qty == 3


async def test_add_beyond_the_cap_reports_over_max_and_writes_nothing(
    session, user, make_product
):
    product = await make_product(max_quantity=3)
    await cart_service.add(session, user, product.id, 3)

    added, problem = await cart_service.add(session, user, product.id, 1)

    assert added == 0
    assert problem is not None
    assert (problem.kind, problem.product_id, problem.allowed_qty) == (
        "over_max",
        product.id,
        3,
    )
    assert (await _rows(session, user))[0].qty == 3, "a refused add still changed the row"


async def test_add_refuses_a_deleted_product(session, user, make_product):
    product = await make_product(is_deleted=True)

    added, problem = await cart_service.add(session, user, product.id, 1)

    assert added == 0
    assert problem.kind == "gone"
    assert await _row_count(session, user) == 0


async def test_add_refuses_an_out_of_stock_product(session, user, make_product):
    product = await make_product(in_stock=False)

    added, problem = await cart_service.add(session, user, product.id, 1)

    assert added == 0
    assert (problem.kind, problem.product_name) == ("out_of_stock", product.name)
    assert await _row_count(session, user) == 0


async def test_add_refuses_a_product_that_never_existed(session, user):
    added, problem = await cart_service.add(session, user, 10**9, 1)

    assert added == 0
    assert problem.kind == "gone"
    assert await _row_count(session, user) == 0


async def test_unique_constraint_prevents_duplicate_lines(session, user, make_product):
    """The constraint, not the service: a hand-written second row must be refused."""
    product = await make_product()
    await cart_service.add(session, user, product.id, 1)

    with pytest.raises(IntegrityError):
        # A SAVEPOINT, so the failure rolls back the duplicate and nothing else.
        async with session.begin_nested():
            session.add(CartItem(user_id=user, product_id=product.id, qty=1))
            await session.flush()

    assert await _row_count(session, user) == 1


# ── reads: price is live, never snapshotted ───────────────────────────────────


async def test_load_lines_carries_the_current_product_state(session, user, make_product):
    product = await make_product(price="4.50", max_quantity=7)
    await cart_service.add(session, user, product.id, 2)

    lines = await cart_service.load_lines(session, user)

    assert len(lines) == 1
    line = lines[0]
    assert (line.product_id, line.qty) == (product.id, 2)
    assert line.product.unit_price == Decimal("4.50")
    assert line.product.max_quantity == 7
    assert (line.product.in_stock, line.product.is_deleted) == (True, False)


async def test_price_read_live_not_snapshotted(session, user, make_product):
    """Changing products.price changes the cart total — there is no stored price."""
    product = await make_product(price="10.00")
    await cart_service.add(session, user, product.id, 3)

    before = pricing.cart_total(await cart_service.load_lines(session, user))
    await product_service.update_price(session, product.id, Decimal("12.00"))
    after = pricing.cart_total(await cart_service.load_lines(session, user))

    assert before == Decimal("30.00")
    assert after == Decimal("36.00")
    # cart_items has no price column to go stale in the first place.
    assert not hasattr(CartItem, "price")


async def test_decimal_survives_round_trip(session, user, make_product):
    product = await make_product(price="0.05")
    await cart_service.add(session, user, product.id, 3)

    lines = await cart_service.load_lines(session, user)
    unit = lines[0].product.unit_price

    assert isinstance(unit, Decimal)
    assert unit == Decimal("0.05")
    assert unit.as_tuple().exponent == -2, "Numeric(10, 2) did not round-trip its scale"
    assert pricing.cart_total(lines) == Decimal("0.15")


async def test_a_cart_row_cannot_point_at_a_missing_product(session, user):
    """cart_items.product_id is a real FK, so load_lines' product=None branch is
    unreachable while the constraint stands: an orphan row cannot be created."""
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add(CartItem(user_id=user, product_id=10**9, qty=1))
            await session.flush()

    assert await _row_count(session, user) == 0


# ── resolve: problems are found and the fix is persisted ──────────────────────


async def test_resolve_is_quiet_for_a_clean_cart(session, user, make_product):
    product = await make_product(price="2.50")
    await cart_service.add(session, user, product.id, 2)

    lines, problems, total = await cart_service.resolve(session, user)

    assert problems == []
    assert [(line.product_id, line.qty) for line in lines] == [(product.id, 2)]
    assert total == Decimal("5.00")


async def test_resolve_drops_deleted_product_and_reports_it(session, user, make_product):
    kept = await make_product(price="3.00")
    doomed = await make_product(price="8.00")
    await cart_service.add(session, user, kept.id, 1)
    await cart_service.add(session, user, doomed.id, 2)
    await product_service.update(session, doomed.id, is_deleted=True)

    lines, problems, total = await cart_service.resolve(session, user)

    assert [(p.kind, p.product_id) for p in problems] == [("gone", doomed.id)]
    assert [line.product_id for line in lines] == [kept.id]
    assert total == Decimal("3.00")
    # The drop is persisted, not just reported.
    assert [(r.product_id, r.qty) for r in await _rows(session, user)] == [(kept.id, 1)]


async def test_resolve_drops_an_out_of_stock_product_and_reports_it(
    session, user, make_product
):
    product = await make_product()
    await cart_service.add(session, user, product.id, 2)
    await product_service.update(session, product.id, in_stock=False)

    lines, problems, total = await cart_service.resolve(session, user)

    assert [(p.kind, p.product_name) for p in problems] == [("out_of_stock", product.name)]
    assert lines == []
    assert total == Decimal("0.00")
    assert await _row_count(session, user) == 0


async def test_resolve_clamps_and_persists_the_clamp(session, user, make_product):
    product = await make_product(price="1.00", max_quantity=10)
    await cart_service.add(session, user, product.id, 8)
    # The admin lowers the cap under what is already in the cart.
    await product_service.update(session, product.id, max_quantity=3)

    lines, problems, total = await cart_service.resolve(session, user)

    assert [(p.kind, p.allowed_qty) for p in problems] == [("over_max", 3)]
    assert [line.qty for line in lines] == [3]
    assert total == Decimal("3.00")
    assert [r.qty for r in await _rows(session, user)] == [3]


async def test_resolve_is_idempotent(session, user, make_product):
    product = await make_product(max_quantity=10)
    await cart_service.add(session, user, product.id, 8)
    await product_service.update(session, product.id, max_quantity=3)

    await cart_service.resolve(session, user)
    lines, problems, _ = await cart_service.resolve(session, user)

    assert problems == [], "the persisted fix did not stick"
    assert [line.qty for line in lines] == [3]


# ── mutations ─────────────────────────────────────────────────────────────────


async def test_set_qty_replaces_the_quantity(session, user, make_product):
    product = await make_product(max_quantity=10)
    await cart_service.add(session, user, product.id, 2)

    problem = await cart_service.set_qty(session, user, product.id, 5)

    assert problem is None
    assert [r.qty for r in await _rows(session, user)] == [5], "set_qty must assign, not add"


async def test_set_qty_clamps_to_max_quantity_and_reports_it(session, user, make_product):
    product = await make_product(max_quantity=4)
    await cart_service.add(session, user, product.id, 1)

    problem = await cart_service.set_qty(session, user, product.id, 9)

    assert (problem.kind, problem.allowed_qty) == ("over_max", 4)
    assert [r.qty for r in await _rows(session, user)] == [4]


async def test_set_qty_to_zero_removes_the_line(session, user, make_product):
    product = await make_product()
    await cart_service.add(session, user, product.id, 2)

    assert await cart_service.set_qty(session, user, product.id, 0) is None
    assert await _row_count(session, user) == 0


async def test_set_qty_on_a_deleted_product_removes_the_line_and_reports_gone(
    session, user, make_product
):
    product = await make_product()
    await cart_service.add(session, user, product.id, 2)
    await product_service.update(session, product.id, is_deleted=True)

    problem = await cart_service.set_qty(session, user, product.id, 1)

    assert (problem.kind, problem.product_id) == ("gone", product.id)
    assert await _row_count(session, user) == 0


async def test_remove_takes_out_one_line_only(session, user, make_product):
    first = await make_product()
    second = await make_product()
    await cart_service.add(session, user, first.id, 1)
    await cart_service.add(session, user, second.id, 2)

    await cart_service.remove(session, user, first.id)

    assert [(r.product_id, r.qty) for r in await _rows(session, user)] == [(second.id, 2)]


async def test_clear_empties_this_cart_only(session, user, other_user, make_product):
    product = await make_product()
    await cart_service.add(session, user, product.id, 1)
    await cart_service.add(session, other_user, product.id, 2)

    await cart_service.clear(session, user)

    assert await _row_count(session, user) == 0
    assert [r.qty for r in await _rows(session, other_user)] == [2]


# ── isolation between customers ───────────────────────────────────────────────


async def test_two_customers_hold_independent_rows_for_one_product(
    session, user, other_user, make_product
):
    """UNIQUE is on (user_id, product_id) — the same product in two carts is two rows."""
    product = await make_product(max_quantity=10)

    await cart_service.add(session, user, product.id, 2)
    await cart_service.add(session, other_user, product.id, 7)

    assert [r.qty for r in await _rows(session, user)] == [2]
    assert [r.qty for r in await _rows(session, other_user)] == [7]


async def test_resolve_only_touches_its_own_cart(session, user, other_user, make_product):
    product = await make_product(max_quantity=10)
    await cart_service.add(session, user, product.id, 6)
    await cart_service.add(session, other_user, product.id, 6)
    await product_service.update(session, product.id, max_quantity=2)

    await cart_service.resolve(session, user)

    assert [r.qty for r in await _rows(session, user)] == [2]
    assert [r.qty for r in await _rows(session, other_user)] == [6], "clamped a stranger's cart"


async def test_a_third_customer_starts_empty(session, user, make_user, make_product):
    product = await make_product()
    await cart_service.add(session, user, product.id, 1)

    newcomer = await make_user()

    assert await cart_service.load_lines(session, newcomer) == []
    assert await _row_count(session, newcomer) == 0


async def test_cart_rows_die_with_their_user(session, user, make_product):
    """ondelete=CASCADE on cart_items.user_id — deleting the account clears the cart."""
    product = await make_product()
    await cart_service.add(session, user, product.id, 1)

    await session.delete(await session.get(User, user))
    await session.commit()

    assert await _row_count(session, user) == 0
