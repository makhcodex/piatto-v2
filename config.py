import os

from dotenv import load_dotenv

load_dotenv()


def _parse_admin_ids(raw: str) -> frozenset[int]:
    """Parse ADMIN_IDS="123,456" into a set. Blank entries are ignored."""
    return frozenset(int(part) for part in raw.replace(" ", "").split(",") if part)


def _normalise_database_url(raw: str) -> str:
    """Force an async driver onto a bare Postgres URL.

    Railway hands out DATABASE_URL as "postgres://..." or "postgresql://...", with
    no driver in the scheme; create_async_engine needs one. Rewrite those two
    schemes to "postgresql+asyncpg://" and leave everything else untouched — a URL
    that already names a driver ("+asyncpg", "+psycopg") keeps it, and so does an
    empty or non-Postgres value, which main.py and db/engine.py report on their own.

    migrations/env.py imports DATABASE_URL from here and is async too, so the
    migrations and the bot always agree on the driver.
    """
    scheme, separator, rest = raw.partition("://")
    if not separator or "+" in scheme:
        return raw
    if scheme in ("postgres", "postgresql"):
        return f"postgresql+asyncpg://{rest}"
    return raw


BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
DATABASE_URL: str = _normalise_database_url(os.getenv("DATABASE_URL", ""))

# Admin identity lives here, not in a staff table. One restaurant, one operator.
ADMIN_IDS: frozenset[int] = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))

# Shown to the customer for the manual transfer. Required at startup: without it
# nobody can pay. Unset, empty, or whitespace-only all parse to "" — main.py aborts.
PAYMENT_CARD_NUMBER: str = os.getenv("PAYMENT_CARD_NUMBER", "").strip()

# Optional branding.
LOGO_URL: str = os.getenv("LOGO_URL", "")

# Payment window, in minutes. The only place these timings live.
WARNING_MINUTES: int = int(os.getenv("WARNING_MINUTES", "10"))
CANCEL_MINUTES: int = int(os.getenv("CANCEL_MINUTES", "20"))

# How often the sweep job runs, in seconds. Job timing is accurate to +/- this.
SWEEP_INTERVAL_SECONDS: int = int(os.getenv("SWEEP_INTERVAL_SECONDS", "60"))

# Orders per user per hour.
ORDER_RATE_LIMIT: int = int(os.getenv("ORDER_RATE_LIMIT", "5"))
