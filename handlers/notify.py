"""Best-effort user notification.

Commit first, notify second: every caller has already committed the state change
before calling this. A blocked user, a deleted chat, or a Telegram outage must
never roll back a status the database already accepted.
"""

import logging

from aiogram import Bot

logger = logging.getLogger(__name__)


async def notify_user(bot: Bot, chat_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id, text)
    except Exception as exc:
        logger.error("Notification to %s failed: %s", chat_id, exc)
