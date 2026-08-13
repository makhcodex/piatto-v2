"""Manual payment confirmation and rejection.

Lives here, not in checkout.py — see handlers/admin/__init__.py for why. The buttons
are built in keyboards/orders.get_admin_payment_keyboard and sent from checkout.py;
this module is the only place their callbacks are handled, and it sits on the admin
router, so IsAdmin already applies. No per-handler admin check belongs below.
"""

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import OrderStatus
from handlers.notify import notify_user
from services import order_service

logger = logging.getLogger(__name__)

router = Router(name="admin.payments")

ALREADY_SETTLED = "Заказ уже обработан"


@router.callback_query(F.data.startswith("pay:confirm:"))
async def confirm_payment(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    order_id = int(callback.data.split(":")[2])

    order = await order_service.settle_payment(session, order_id, OrderStatus.PAID)
    if order is None:
        await callback.answer(ALREADY_SETTLED, show_alert=True)
        return

    logger.info("Payment for order #%d confirmed by admin %s", order.id, callback.from_user.id)
    # Committed first, notified after: the customer's chat cannot roll back the status.
    await notify_user(
        bot, order.user.telegram_id, f"✅ Оплата подтверждена, заказ #{order.id} принят."
    )
    await _settle_message(callback, "✅ Подтверждено")
    await callback.answer()


@router.callback_query(F.data.startswith("pay:reject:"))
async def reject_payment(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    order_id = int(callback.data.split(":")[2])

    order = await order_service.settle_payment(session, order_id, OrderStatus.CANCELLED_UNPAID)
    if order is None:
        await callback.answer(ALREADY_SETTLED, show_alert=True)
        return

    logger.info("Payment for order #%d rejected by admin %s", order.id, callback.from_user.id)
    await notify_user(
        bot, order.user.telegram_id, f"❌ Оплата отклонена, заказ #{order.id} отменён."
    )
    await _settle_message(callback, "❌ Отклонено")
    await callback.answer()


async def _settle_message(callback: CallbackQuery, mark: str) -> None:
    """Drop the buttons and record the decision in the admin's own message.

    html_text, not text: the notification is HTML and plain text would lose the
    formatting on the way back in.
    """
    message = callback.message
    if not isinstance(message, Message):
        return

    try:
        if message.text:
            await message.edit_text(f"{message.html_text}\n\n{mark}", reply_markup=None)
        else:
            await message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError as exc:
        # Message too old, already edited, identical content — none of it undoes the
        # committed status change.
        logger.error("Editing the admin message for order decision failed: %s", exc)
