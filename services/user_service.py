"""User lookup and registration."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User


async def get_or_create(
    session: AsyncSession, telegram_id: int, username: str | None = None
) -> int:
    """Return users.id — the internal primary key, not the Telegram id.

    Every handler calls this first. Everything downstream (cart_items.user_id,
    orders.user_id) keys off the internal id.
    """
    user = (
        await session.execute(select(User).where(User.telegram_id == telegram_id))
    ).scalar_one_or_none()

    if user is None:
        user = User(telegram_id=telegram_id, username=username)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    elif username and user.username != username:
        user.username = username
        await session.commit()

    return user.id


async def set_phone(session: AsyncSession, user_id: int, phone: str) -> None:
    raise NotImplementedError
