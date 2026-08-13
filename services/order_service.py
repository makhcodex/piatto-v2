"""Order lifecycle. The only place a price snapshot is ever taken."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import ORDER_RATE_LIMIT
from db.models import ACTIVE_STATUSES, NEXT_STATUS, CartItem, Order, OrderItem, OrderStatus
from domain import cart_rules, pricing
from domain.models import CartProblem
from services import cart_service

logger = logging.getLogger(__name__)


class CartNotOrderable(Exception):
    """Cart could not be ordered as-is. Carries facts; the handler renders them."""

    def __init__(self, problems: list[CartProblem]) -> None:
        self.problems = problems
        super().__init__(f"{len(problems)} cart problem(s)")


class RateLimitExceeded(Exception):
    """Too many orders in the last hour. Enforced here, never in a handler."""

    def __init__(self, placed: int, limit: int = ORDER_RATE_LIMIT) -> None:
        self.placed = placed
        self.limit = limit
        super().__init__(f"{placed} orders in the last hour, limit is {limit}")


async def orders_in_last_hour(session: AsyncSession, user_id: int) -> int:
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    return (
        await session.execute(
            select(func.count(Order.id)).where(Order.user_id == user_id, Order.created_at >= since)
        )
    ).scalar() or 0


async def create_order(
    session: AsyncSession,
    user_id: int,
    address: str,
    contact_name: str,
    contact_phone: str,
) -> Order:
    """Turn the persisted cart into an order, in one transaction.

    Raises CartNotOrderable if the cart changed underneath the user — the caller
    shows the problems and lets them retry. Raises RateLimitExceeded past the hourly
    limit. Reads the cart from the database, not from a caller-supplied dict: there
    is one cart, and it lives in cart_items.
    """
    placed = await orders_in_last_hour(session, user_id)
    if placed >= ORDER_RATE_LIMIT:
        raise RateLimitExceeded(placed)

    lines = await cart_service.load_lines(session, user_id)
    if not lines:
        raise CartNotOrderable([])

    problems = cart_rules.check(lines)
    if problems:
        raise CartNotOrderable(problems)

    total = pricing.cart_total(lines)

    try:
        order = Order(
            user_id=user_id,
            status=OrderStatus.PENDING,
            total_price=total,
            address=address,
            contact_name=contact_name,
            contact_phone=contact_phone,
        )
        session.add(order)
        await session.flush()

        session.add_all(
            OrderItem(
                order_id=order.id,
                product_id=line.product_id,
                quantity=line.qty,
                # The snapshot. Immutable from here on.
                price=line.product.unit_price,
            )
            for line in lines
        )

        # Cart is emptied inside the same transaction as the order.
        await session.execute(delete(CartItem).where(CartItem.user_id == user_id))
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("Order creation failed for user %s", user_id)
        raise

    return order


async def get_with_user(session: AsyncSession, order_id: int) -> Order | None:
    """The order plus everything a handler renders: customer, items, their products.

    Eager all the way down. The session is async, so a lazy load reached from a
    handler raises instead of quietly issuing a query.
    """
    return (
        await session.execute(
            select(Order)
            .options(
                selectinload(Order.user),
                selectinload(Order.items).selectinload(OrderItem.product),
            )
            .where(Order.id == order_id)
        )
    ).scalar_one_or_none()


async def set_status(session: AsyncSession, order_id: int, status: OrderStatus) -> Order | None:
    order = await get_with_user(session, order_id)
    if order is None:
        return None
    order.status = status
    await session.commit()
    return order


async def settle_payment(
    session: AsyncSession, order_id: int, status: OrderStatus
) -> Order | None:
    """Confirm (PAID) or reject (CANCELLED_UNPAID) a payment awaiting a decision.

    Only PENDING moves. Returns None when the order is gone or already settled —
    a second tap on the admin buttons must not overwrite a decision, and must not
    undo an auto-cancel the sweep already made. The caller reports that fact; the
    guard lives here so no handler has to compare statuses.
    """
    order = await get_with_user(session, order_id)
    if order is None or order.status != OrderStatus.PENDING:
        return None
    order.status = status
    await session.commit()
    return order


async def advance_status(session: AsyncSession, order_id: int) -> Order | None:
    """Move an order to the next status an admin may set."""
    order = await get_with_user(session, order_id)
    if order is None or order.status not in NEXT_STATUS:
        return None
    order.status = NEXT_STATUS[order.status]
    await session.commit()
    return order


async def list_active(session: AsyncSession) -> list[Order]:
    result = await session.execute(
        select(Order)
        .options(selectinload(Order.user))
        .where(Order.status.in_(ACTIVE_STATUSES))
        .order_by(Order.created_at.desc())
    )
    return list(result.scalars())
