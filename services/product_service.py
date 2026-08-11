"""Product reads and admin CRUD.

TODO: fill in during implementation. Signatures are fixed by the architecture:
services own the session, callers never see ORM rows leak into handlers.
"""

from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Product


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
    raise NotImplementedError


async def update(session: AsyncSession, product_id: int, **fields) -> Product | None:
    raise NotImplementedError


async def soft_delete(session: AsyncSession, product_id: int) -> bool:
    """Sets is_deleted. Never hard-deletes — order_items reference products forever."""
    raise NotImplementedError


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
