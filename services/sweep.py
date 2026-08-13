"""Payment reminder and auto-cancel, as one periodic sweep.

Replaces v1's two per-order date jobs. All state lives in `orders`, so there is
nothing to persist and nothing that can desync from the orders table. A restart
loses nothing: the next pass picks up whatever is overdue.

Trade accepted: firing time is accurate to +/- SWEEP_INTERVAL_SECONDS.
"""

import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import ADMIN_IDS, CANCEL_MINUTES, SWEEP_INTERVAL_SECONDS, WARNING_MINUTES
from db.engine import get_session_factory
from db.models import Order, OrderStatus

logger = logging.getLogger(__name__)


async def orders_pending_warning(session: AsyncSession) -> list[Order]:
    """Pending orders past the reminder mark, not yet cancelled, not yet warned."""
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(Order)
        .options(selectinload(Order.user))
        .where(
            Order.status == OrderStatus.PENDING,
            Order.warning_sent.is_(False),
            Order.created_at <= now - timedelta(minutes=WARNING_MINUTES),
            Order.created_at > now - timedelta(minutes=CANCEL_MINUTES),
        )
    )
    return list(result.scalars())


async def orders_to_auto_cancel(session: AsyncSession) -> list[Order]:
    """Pending orders past the cancel mark."""
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(Order)
        .options(selectinload(Order.user))
        .where(
            Order.status == OrderStatus.PENDING,
            Order.created_at <= now - timedelta(minutes=CANCEL_MINUTES),
        )
    )
    return list(result.scalars())


async def run_once(bot: Bot) -> None:
    """One sweep pass. Idempotent — safe to run at any frequency."""
    async with get_session_factory()() as session:
        for order in await orders_pending_warning(session):
            order.warning_sent = True
            await session.commit()
            await _notify(
                bot,
                order.user.telegram_id,
                f"⚠️ Order #{order.id} is still awaiting payment. "
                f"It will be cancelled automatically soon.",
            )

        for order in await orders_to_auto_cancel(session):
            order.status = OrderStatus.CANCELLED_UNPAID
            await session.commit()
            logger.warning("AUTO-CANCEL: order #%d cancelled (unpaid)", order.id)
            await _notify(
                bot,
                order.user.telegram_id,
                f"❌ Order #{order.id} was cancelled automatically — payment not received "
                f"within {CANCEL_MINUTES} minutes.",
            )
            for admin_id in ADMIN_IDS:
                await _notify(bot, admin_id, f"⏱ Order #{order.id} auto-cancelled (unpaid)")


async def _notify(bot: Bot, chat_id: int, text: str) -> None:
    """A failed notification must not abort the sweep — the DB change already committed.

    Intentional duplication of handlers/notify.notify_user — sweep is a service and
    must not import from the handler layer.
    """
    try:
        await bot.send_message(chat_id, text)
    except Exception as exc:
        logger.error("SWEEP: notification to %s failed: %s", chat_id, exc)


def create_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_once,
        trigger="interval",
        seconds=SWEEP_INTERVAL_SECONDS,
        kwargs={"bot": bot},
        id="payment_sweep",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return scheduler
