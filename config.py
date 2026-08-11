import os

from dotenv import load_dotenv

load_dotenv()


def _parse_admin_ids(raw: str) -> frozenset[int]:
    """Parse ADMIN_IDS="123,456" into a set. Blank entries are ignored."""
    return frozenset(int(part) for part in raw.replace(" ", "").split(",") if part)


BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
DATABASE_URL: str = os.getenv("DATABASE_URL", "")
LOGO_URL: str = os.getenv("LOGO_URL", "")

# Admin identity lives here, not in a staff table. One restaurant, one operator.
ADMIN_IDS: frozenset[int] = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))

# Payment window, in minutes.
PAYMENT_REMINDER_AFTER: int = int(os.getenv("PAYMENT_REMINDER_AFTER", "10"))
PAYMENT_CANCEL_AFTER: int = int(os.getenv("PAYMENT_CANCEL_AFTER", "20"))

# How often the sweep job runs, in seconds. Job timing is accurate to +/- this.
SWEEP_INTERVAL_SECONDS: int = int(os.getenv("SWEEP_INTERVAL_SECONDS", "60"))

# Orders per user per hour.
RATE_LIMIT: int = int(os.getenv("RATE_LIMIT", "5"))
