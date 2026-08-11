from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import DATABASE_URL

_engine = None
_session_factory = None


def _make_engine():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set. Check your .env file.")
    return create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)


def get_engine():
    """Lazy singleton — created on first access so import-time errors stay clear."""
    global _engine
    if _engine is None:
        _engine = _make_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return _session_factory


async def dispose_engine() -> None:
    """Close the connection pool on shutdown."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
