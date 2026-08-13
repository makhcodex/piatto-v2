"""Dump the most recent order for eyeball inspection after a live run.

    python -m scripts.inspect_last_order

Read-only: no INSERT, UPDATE or DELETE. Temporary diagnostic tool, not part of the
application and not intended to be committed.

Checks worth watching:
  - status prints in UPPER CASE (SQLAlchemy stores enum member names)
  - order_items.price is the snapshot; products.price is live and may differ
  - cart_items for this user should be empty (create_order clears it in the same
    transaction)
  - both money values must be Decimal, never float
"""

import asyncio

from sqlalchemy import select

from db.engine import dispose_engine, get_session_factory
from db.models import CartItem, Order, OrderItem, Product, User


async def inspect() -> None:
    async with get_session_factory()() as session:
        order = (
            await session.execute(select(Order).order_by(Order.id.desc()).limit(1))
        ).scalar_one_or_none()

        if order is None:
            print("No orders yet.")
            return

        user = await session.get(User, order.user_id)

        print("=" * 60)
        print(f"order id       : {order.id}")
        print(f"status         : {order.status!r}")
        print(f"total_price    : {order.total_price!r}   type={type(order.total_price).__name__}")
        print(f"created_at     : {order.created_at}")
        print(f"contact_name   : {order.contact_name!r}")
        print(f"contact_phone  : {order.contact_phone!r}")
        print(f"address        : {order.address!r}")
        print(f"warning_sent   : {order.warning_sent}")
        print(f"user_id        : {order.user_id}  (telegram_id={user.telegram_id if user else '?'})")

        items = list(
            (
                await session.execute(
                    select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.id)
                )
            ).scalars()
        )

        print("-" * 60)
        print(f"{'product_id':>10} {'qty':>4} {'snapshot':>12} {'live now':>12}  name")
        for item in items:
            product = await session.get(Product, item.product_id)
            live = product.price if product else None
            flag = "" if live == item.price else "   <-- price moved since the order"
            print(
                f"{item.product_id:>10} {item.quantity:>4} {item.price!s:>12} "
                f"{live!s:>12}  {product.name if product else '(gone)'}{flag}"
            )
            print(
                f"{'':>10} {'':>4} type={type(item.price).__name__}"
            )

        remaining = list(
            (
                await session.execute(select(CartItem).where(CartItem.user_id == order.user_id))
            ).scalars()
        )

        print("-" * 60)
        if remaining:
            print(f"cart_items for this user: {len(remaining)} row(s) — EXPECTED 0")
            for row in remaining:
                print(f"  product_id={row.product_id} qty={row.qty}")
        else:
            print("cart_items for this user: empty (as expected)")

        decimals_ok = type(order.total_price).__name__ == "Decimal" and all(
            type(item.price).__name__ == "Decimal" for item in items
        )
        print(f"all money is Decimal: {decimals_ok}")
        print("=" * 60)


async def main() -> None:
    try:
        await inspect()
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
