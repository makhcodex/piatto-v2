"""Category reads and admin CRUD.

`list_all` is the customer read and hides soft-deleted rows; `list_for_admin` shows
them. Deleting a category is guarded: a category with live products in it cannot be
hidden, or the products would vanish from the catalogue with no way to reach them.
"""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Category
from services import product_service


async def list_all(session: AsyncSession) -> list[Category]:
    result = await session.execute(
        select(Category).where(Category.is_deleted.is_(False)).order_by(Category.name)
    )
    return list(result.scalars())


async def list_for_admin(session: AsyncSession) -> list[Category]:
    """Every category including soft-deleted ones."""
    result = await session.execute(select(Category).order_by(Category.name))
    return list(result.scalars())


async def get(session: AsyncSession, category_id: int) -> Category | None:
    return await session.get(Category, category_id)


async def get_by_slug(session: AsyncSession, slug: str) -> Category | None:
    return (
        await session.execute(select(Category).where(Category.slug == slug))
    ).scalar_one_or_none()


async def slug_taken(session: AsyncSession, slug: str) -> bool:
    """Unique-slug pre-check, so a duplicate is a message and not a crash."""
    return await get_by_slug(session, slug) is not None


async def create(session: AsyncSession, *, slug: str, name: str) -> Category:
    if not slug.strip():
        raise ValueError("slug must not be empty")
    if not name.strip():
        raise ValueError("name must not be empty")

    category = Category(slug=slug, name=name)
    session.add(category)
    await session.commit()
    return category


async def rename(session: AsyncSession, category_id: int, name: str) -> Category | None:
    if not name.strip():
        raise ValueError("name must not be empty")

    category = await session.get(Category, category_id)
    if category is None:
        return None
    category.name = name
    await session.commit()
    return category


async def toggle_deleted(session: AsyncSession, category_id: int) -> Category | None:
    """Hide or restore a category.

    Returns None when the move is not allowed: no such category, or hiding one that
    still holds live products. Restoring is never blocked. The caller reports the
    reason — it can tell the two apart with product_service.count_in_category.
    """
    category = await session.get(Category, category_id)
    if category is None:
        return None

    if not category.is_deleted and await product_service.count_in_category(session, category_id):
        return None

    category.is_deleted = not category.is_deleted
    await session.commit()
    return category


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
    """Hide a category. False when it is missing or still holds live products."""
    category = await session.get(Category, category_id)
    if category is None:
        return False
    if category.is_deleted:
        return True
    if await product_service.count_in_category(session, category_id):
        return False

    category.is_deleted = True
    await session.commit()
    return True
