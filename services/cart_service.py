"""Cart persistence and the bridge into domain/.

This is the reference example of the layering: fetch rows, convert to domain
value objects, let domain decide, write the decision back. No rule is decided here.
"""

from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import CartItem, Product
from domain import cart_rules, pricing
from domain.models import CartLine, CartProblem, ProductView


def to_view(product: Product) -> ProductView:
    """The only place a DB row becomes a domain value."""
    return ProductView(
        id=product.id,
        name=product.name,
        unit_price=product.price,
        max_quantity=product.max_quantity,
        in_stock=product.in_stock,
        is_deleted=product.is_deleted,
    )


async def load_lines(session: AsyncSession, user_id: int) -> list[CartLine]:
    """Read the cart as domain values. One batch query, no N+1."""
    rows = list(
        (
            await session.execute(
                select(CartItem, Product)
                .outerjoin(Product, Product.id == CartItem.product_id)
                .where(CartItem.user_id == user_id)
                .order_by(CartItem.id)
            )
        ).all()
    )
    return [
        CartLine(
            product_id=item.product_id,
            qty=item.qty,
            product=to_view(product) if product is not None else None,
        )
        for item, product in rows
    ]


async def resolve(
    session: AsyncSession, user_id: int
) -> tuple[list[CartLine], list[CartProblem], Decimal]:
    """Validate the cart, persist any corrections, return the priced result.

    Returns (resolved_lines, problems, total). Problems are facts — the handler
    turns them into text.
    """
    lines = await load_lines(session, user_id)
    problems = cart_rules.check(lines)

    if problems:
        resolved = cart_rules.apply(lines)
        await _persist(session, user_id, resolved)
        await session.commit()
    else:
        resolved = lines

    return resolved, problems, pricing.cart_total(resolved)


async def add(
    session: AsyncSession, user_id: int, product_id: int, qty: int
) -> tuple[int, CartProblem | None]:
    """Add `qty` units, capped by what the cart has room for.

    Returns (units_actually_added, problem_or_None). Adds to the existing
    quantity — never overwrites it. v1's bug #6 was validating as an addition
    and then assigning the result.
    """
    product = await session.get(Product, product_id)
    if product is None or product.is_deleted:
        return 0, CartProblem(product_id=product_id, kind="gone")
    if not product.in_stock:
        return 0, CartProblem(product_id=product_id, kind="out_of_stock", product_name=product.name)

    view = to_view(product)
    item = await _get_item(session, user_id, product_id)
    line = CartLine(product_id, item.qty, view) if item else None

    allowed = cart_rules.allowed_to_add(line, view, qty)
    if allowed == 0:
        return 0, CartProblem(
            product_id=product_id,
            kind="over_max",
            product_name=product.name,
            allowed_qty=view.max_quantity,
        )

    if item is None:
        session.add(CartItem(user_id=user_id, product_id=product_id, qty=allowed))
    else:
        item.qty += allowed

    await session.commit()
    return allowed, None


async def set_qty(
    session: AsyncSession, user_id: int, product_id: int, qty: int
) -> CartProblem | None:
    """Set an absolute quantity (edit-in-cart). qty <= 0 removes the line."""
    if qty <= 0:
        await remove(session, user_id, product_id)
        return None

    product = await session.get(Product, product_id)
    if product is None or product.is_deleted:
        await remove(session, user_id, product_id)
        return CartProblem(product_id=product_id, kind="gone")

    problem: CartProblem | None = None
    if qty > product.max_quantity:
        problem = CartProblem(
            product_id=product_id,
            kind="over_max",
            product_name=product.name,
            allowed_qty=product.max_quantity,
        )
        qty = product.max_quantity

    item = await _get_item(session, user_id, product_id)
    if item is None:
        session.add(CartItem(user_id=user_id, product_id=product_id, qty=qty))
    else:
        item.qty = qty

    await session.commit()
    return problem


async def remove(session: AsyncSession, user_id: int, product_id: int) -> None:
    await session.execute(
        delete(CartItem).where(CartItem.user_id == user_id, CartItem.product_id == product_id)
    )
    await session.commit()


async def clear(session: AsyncSession, user_id: int) -> None:
    await session.execute(delete(CartItem).where(CartItem.user_id == user_id))
    await session.commit()


async def _get_item(session: AsyncSession, user_id: int, product_id: int) -> CartItem | None:
    return (
        await session.execute(
            select(CartItem).where(
                CartItem.user_id == user_id, CartItem.product_id == product_id
            )
        )
    ).scalar_one_or_none()


async def _persist(session: AsyncSession, user_id: int, resolved: list[CartLine]) -> None:
    """Write resolved lines back: drop what disappeared, clamp what exceeded the limit."""
    keep = {line.product_id: line.qty for line in resolved}

    for item in (
        await session.execute(select(CartItem).where(CartItem.user_id == user_id))
    ).scalars():
        if item.product_id not in keep:
            await session.delete(item)
        elif item.qty != keep[item.product_id]:
            item.qty = keep[item.product_id]
