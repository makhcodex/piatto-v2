"""Product reads and admin CRUD.

TODO: fill in during implementation. Signatures are fixed by the architecture:
services own the session, callers never see ORM rows leak into handlers.
"""

from decimal import Decimal

from sqlalchemy import select
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
