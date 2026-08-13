"""Product reads and admin CRUD.

Two kinds of read live here. The customer reads (`get`, `list_by_category`) hide
soft-deleted rows; the admin reads (`get_for_admin`, `list_for_admin`) show them,
because the admin is the only one who can bring one back.
"""

from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import Category, Product

# products.price is Numeric(10, 2): eight digits before the point, two after.
PRICE_MAX = Decimal("99999999.99")

# Columns an admin may write through update(). Anything outside this set is a caller
# bug, not user input — hence ValueError rather than a returned fact.
EDITABLE = frozenset({
    "category_id", "name", "description", "price",
    "image_url", "in_stock", "max_quantity", "is_deleted",
})


async def get(session: AsyncSession, product_id: int) -> Product | None:
    product = await session.get(Product, product_id)
    return None if product is None or product.is_deleted else product


async def list_by_category(session: AsyncSession, category_id: int) -> list[Product]:
    result = await session.execute(
        select(Product)
        .where(Product.category_id == category_id, Product.is_deleted.is_(False))
        .order_by(Product.name)
    )
    return list(result.scalars())


async def get_for_admin(session: AsyncSession, product_id: int) -> Product | None:
    """Any product, deleted or not, with its category loaded for rendering."""
    return (
        await session.execute(
            select(Product)
            .options(selectinload(Product.category))
            .where(Product.id == product_id)
        )
    ).scalar_one_or_none()


async def list_for_admin(session: AsyncSession) -> list[Product]:
    """Every product including soft-deleted ones, ordered so the caller can group."""
    result = await session.execute(
        select(Product)
        .options(selectinload(Product.category))
        .join(Product.category)
        .order_by(Category.name, Product.name)
    )
    return list(result.scalars())


async def count_in_category(session: AsyncSession, category_id: int) -> int:
    """Live products in a category. The guard behind category_service.toggle_deleted."""
    return (
        await session.execute(
            select(func.count(Product.id)).where(
                Product.category_id == category_id, Product.is_deleted.is_(False)
            )
        )
    ).scalar() or 0


async def name_taken(session: AsyncSession, name: str) -> bool:
    """uq_products_name pre-check, so a duplicate is a message and not a crash."""
    return (
        await session.execute(select(Product.id).where(Product.name == name))
    ).first() is not None


async def create(
    session: AsyncSession,
    *,
    category_id: int,
    name: str,
    price: Decimal,
    description: str | None = None,
    image_url: str | None = None,
    max_quantity: int = 10,
) -> Product:
    """Validates here, once. The handler parses input; the rules live in the service."""
    check_name(name)
    check_price(price)
    check_quantity(max_quantity)

    product = Product(
        category_id=category_id,
        name=name,
        price=price,
        description=description,
        image_url=image_url,
        max_quantity=max_quantity,
    )
    session.add(product)
    await session.commit()
    return product


async def update(session: AsyncSession, product_id: int, **fields) -> Product | None:
    """Write whitelisted columns. Returns None when there is no such product."""
    unknown = set(fields) - EDITABLE
    if unknown:
        raise ValueError(f"not editable: {sorted(unknown)}")

    product = await session.get(Product, product_id)
    if product is None:
        return None

    for column, value in fields.items():
        setattr(product, column, value)
    await session.commit()
    return product


async def update_price(
    session: AsyncSession, product_id: int, price: Decimal
) -> Product | None:
    check_price(price)
    return await update(session, product_id, price=price)


async def update_max_quantity(
    session: AsyncSession, product_id: int, max_quantity: int
) -> Product | None:
    check_quantity(max_quantity)
    return await update(session, product_id, max_quantity=max_quantity)


async def toggle_in_stock(session: AsyncSession, product_id: int) -> Product | None:
    product = await session.get(Product, product_id)
    if product is None:
        return None
    return await update(session, product_id, in_stock=not product.in_stock)


async def toggle_deleted(session: AsyncSession, product_id: int) -> Product | None:
    """Soft delete and restore, the same button in both directions."""
    product = await session.get(Product, product_id)
    if product is None:
        return None
    return await update(session, product_id, is_deleted=not product.is_deleted)


async def soft_delete(session: AsyncSession, product_id: int) -> bool:
    """Sets is_deleted. Never hard-deletes — order_items reference products forever."""
    return await update(session, product_id, is_deleted=True) is not None


# Public on purpose. A wizard has to reject a bad price at the step where it was
# typed, not three steps later at create() — so it calls the same check, and the
# rule still exists exactly once. Handlers parse input; these say what is valid.


def check_name(name: str) -> None:
    if not name.strip():
        raise ValueError("name must not be empty")


def check_price(price: Decimal) -> None:
    # Decimal, never float — comparing a price to zero is still money arithmetic.
    # The upper bound is the column, Numeric(10, 2), not a business rule: past it
    # Postgres raises and the admin gets a stack trace instead of a sentence.
    if not price.is_finite() or price <= Decimal("0") or price > PRICE_MAX:
        raise ValueError("price must be greater than zero and fit Numeric(10, 2)")


def check_quantity(max_quantity: int) -> None:
    if max_quantity < 1:
        raise ValueError("max_quantity must be at least 1")


async def upsert_seed(
    session: AsyncSession,
    *,
    category_id: int,
    name: str,
    price: Decimal,
    description: str | None = None,
    max_quantity: int = 10,
) -> tuple[int, bool]:
    """Insert or refresh a seed product by name. Returns (products.id, was_inserted).

    Price is written on insert only. On conflict every other column is refreshed but
    `price` is deliberately left alone: the admin edits prices in the bot, and a
    re-seed must never undo that. v1 overwrote prices on every startup.
    """
    statement = (
        insert(Product)
        .values(
            category_id=category_id,
            name=name,
            price=price,
            description=description,
            max_quantity=max_quantity,
            in_stock=True,
            is_deleted=False,
        )
        .on_conflict_do_update(
            constraint="uq_products_name",
            set_={
                "category_id": category_id,
                "description": description,
                "max_quantity": max_quantity,
                "in_stock": True,
                "is_deleted": False,
                # "price" is absent on purpose. Do not add it.
            },
        )
        # xmax is 0 only on a fresh insert — the reliable way to tell the two apart.
        .returning(Product.id, text("xmax = 0"))
    )
    product_id, inserted = (await session.execute(statement)).one()
    await session.commit()
    return product_id, inserted
