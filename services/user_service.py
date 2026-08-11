"""User lookup and registration."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User


async def get_or_create(
    session: AsyncSession, telegram_id: int, username: str | None = None
) -> User:
    """Every handler needs the internal user id; this is the single entry point."""
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

    return user


async def set_phone(session: AsyncSession, user_id: int, phone: str) -> None:
    raise NotImplementedError
