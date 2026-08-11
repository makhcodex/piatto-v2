"""Category reads and admin CRUD. TODO: fill in during implementation."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
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


async def upsert(session: AsyncSession, *, slug: str, name: str) -> int:
    """Insert or refresh a category by slug, returning categories.id.

    Used by scripts/seed.py. Re-seeding renames a category but never duplicates it,
    and un-deletes one that was soft-deleted.
    """
    statement = (
        insert(Category)
        .values(slug=slug, name=name, is_deleted=False)
        .on_conflict_do_update(
            index_elements=[Category.slug],
            set_={"name": name, "is_deleted": False},
        )
        .returning(Category.id)
    )
    category_id = (await session.execute(statement)).scalar_one()
    await session.commit()
    return category_id


async def soft_delete(session: AsyncSession, category_id: int) -> bool:
    raise NotImplementedError
