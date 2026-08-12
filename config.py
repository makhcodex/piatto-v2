import os

from dotenv import load_dotenv

load_dotenv()


def _parse_admin_ids(raw: str) -> frozenset[int]:
    """Parse ADMIN_IDS="123,456" into a set. Blank entries are ignored."""
    return frozenset(int(part) for part in raw.replace(" ", "").split(",") if part)


BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
DATABASE_URL: str = os.getenv("DATABASE_URL", "")

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
