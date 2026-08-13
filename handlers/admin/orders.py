"""Active order browsing and status advancement.

Callback data, mirroring the `pay:` scheme in payments.py:

    order:list             back to the list of active orders
    order:detail:{id}      show one order in full
    order:advance:{id}     move it to the next status

`order:claim:{id}` belongs to the customer side (handlers/checkout.py) and is not
handled here. The prefixes do not overlap, so the admin router — included first in
handlers/__init__.py — shadows nothing a customer can press.

This module never decides which status follows which: db/models.NEXT_STATUS owns the
chain, order_service.advance_status walks it, and the handler only asks whether a next
status exists so it knows whether to draw the button.
"""

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import NEXT_STATUS, Order
from handlers import render
from keyboards.orders import get_order_detail_keyboard, get_orders_list_keyboard
from services import order_service

logger = logging.getLogger(__name__)

router = Router(name="admin.orders")

NO_ACTIVE = "Нет активных заказов"
GONE = "Заказ не найден"
TERMINAL = "Заказ уже в финальном статусе"
NO_CONTACT = "—"


@router.message(Command("orders"))
async def cmd_orders(message: Message, session: AsyncSession) -> None:
    text, keyboard = await _list_view(session)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data == "order:list")
async def back_to_list(callback: CallbackQuery, session: AsyncSession) -> None:
    text, keyboard = await _list_view(session)
    await _show(callback, text, keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("order:detail:"))
async def show_detail(callback: CallbackQuery, session: AsyncSession) -> None:
    order_id = int(callback.data.split(":")[2])

    order = await order_service.get_with_user(session, order_id)
    if order is None:
        await callback.answer(GONE, show_alert=True)
        return

    await _show(callback, _detail_text(order), _detail_keyboard(order))
    await callback.answer()


@router.callback_query(F.data.startswith("order:advance:"))
async def advance_status(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    order_id = int(callback.data.split(":")[2])

    # None means "there was nowhere to move it": terminal status, or no such order.
    order = await order_service.advance_status(session, order_id)
    if order is None:
        await callback.answer(TERMINAL, show_alert=True)
        return

    logger.info(
        "Order #%d advanced to %s by admin %s", order.id, order.status, callback.from_user.id
    )
    # Committed by the service first, announced after — the customer's chat cannot
    # roll back a status the database already accepted.
    await _notify(
        bot,
        order.user.telegram_id,
        f"📦 Заказ #{order.id}: {render.status_label(order.status)}",
    )
    await _show(callback, _detail_text(order), _detail_keyboard(order))
    await callback.answer()


async def _list_view(session: AsyncSession) -> tuple[str, InlineKeyboardMarkup | None]:
    orders = await order_service.list_active(session)
    if not orders:
        return NO_ACTIVE, None

    rows = "\n\n".join(_summary(order) for order in orders)
    text = f"📋 <b>Активные заказы</b> ({len(orders)})\n\n{rows}"
    buttons = [
        (order.id, f"#{order.id} · {render.status_label(order.status)}") for order in orders
    ]
    return text, get_orders_list_keyboard(buttons)


def _summary(order: Order) -> str:
    return (
        f"<b>#{order.id}</b> · {render.status_label(order.status)}\n"
        f"{render.money(order.total_price)} · {_created(order)}\n"
        f"👤 {_contact(order)}"
    )


def _detail_text(order: Order) -> str:
    items = "\n".join(
        f"• <b>{_product_name(item)}</b> × {item.quantity} — "
        f"{render.money(item.price)} за шт."
        for item in order.items
    )
    return (
        f"📦 <b>Заказ #{order.id}</b>\n"
        f"Статус: {render.status_label(order.status)}\n"
        f"Создан: {_created(order)}\n\n"
        f"{items}\n\n"
        f"<b>Итого: {render.money(order.total_price)}</b>\n\n"
        f"👤 {_contact(order)}\n"
        f"📍 {order.address}"
    )


def _detail_keyboard(order: Order) -> InlineKeyboardMarkup:
    next_status = NEXT_STATUS.get(order.status)
    return get_order_detail_keyboard(
        order.id, render.status_label(next_status) if next_status else None
    )


def _product_name(item) -> str:
    # Products are soft-deleted, so this normally resolves; the fallback keeps a
    # broken row from taking the whole view down.
    return item.product.name if item.product is not None else f"#{item.product_id}"


def _contact(order: Order) -> str:
    parts = [part for part in (order.contact_name, order.contact_phone) if part]
    return " · ".join(parts) if parts else NO_CONTACT


def _created(order: Order) -> str:
    # created_at is stored with a timezone and comes back as UTC. Said out loud,
    # because an admin reading a delivery time must not guess the offset.
    return f"{order.created_at:%d.%m.%Y %H:%M} UTC"


async def _show(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup | None) -> None:
    """Render in place; fall back to a new message when the old one cannot be edited."""
    message = callback.message
    if not isinstance(message, Message):
        return

    try:
        await message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest:
        # Identical content, or a message too old to edit.
        await message.answer(text, reply_markup=keyboard)


async def _notify(bot: Bot, chat_id: int, text: str) -> None:
    """Best effort, as in payments._notify — the customer may have blocked the bot."""
    try:
        await bot.send_message(chat_id, text)
    except Exception as exc:
        logger.error("Status notification to %s failed: %s", chat_id, exc)
