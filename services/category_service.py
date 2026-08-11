"""Category reads and admin CRUD. TODO: fill in during implementation."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Category


async def list_all(session: AsyncSession) -> list[Category]:
    result = await session.execute(
        select(Category).where(Category.is_deleted.is_(False)).order_by(Category.name)
    )
    return list(result.scalars())


async def get_by_slug(session: AsyncSession, slug: str) -> Category | None:
    return (
        await session.execute(select(Category).where(Category.slug == slug))
    ).scalar_one_or_none()


async def create(session: AsyncSession, *, slug: str, name: str) -> Category:
    raise NotImplementedError


async def soft_delete(session: AsyncSession, category_id: int) -> bool:
    raise NotImplementedError
