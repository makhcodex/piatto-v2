"""The customer's own order history.

The admin counterpart is handlers/admin/orders.py and shares nothing with this: that
one lists every customer's orders and can advance a status, this one reads back what
the caller placed and can change nothing.

Callback data, splitting the `order:` prefix by action:

    order:mine          back to the caller's own list
    order:view:{id}     one of the caller's orders in full

Neither collides with the admin router's `order:list` / `order:detail:` /
`order:advance:`, nor with checkout's `order:claim:`. The admin router is included
first, so an overlapping action segment would be shadowed — these do not overlap.

Every read here goes through order_service.get_for_user / list_for_user, which filter
by user_id. get_with_user is the admin read and must not appear below.
"""

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Order
from handlers import render
from services import order_service, user_service

router = Router(name="orders")

EMPTY = "📦 You have no orders yet."
HEADER = "📦 <b>Your orders</b>"
GONE = "Order not found"


@router.message(F.text == "📦 My Orders")
async def show_orders(message: Message, session: AsyncSession) -> None:
    user_id = await user_service.get_or_create(
        session, message.from_user.id, message.from_user.username
    )
    text, keyboard = await _list_view(session, user_id)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data == "order:mine")
async def back_to_list(callback: CallbackQuery, session: AsyncSession) -> None:
    user_id = await user_service.get_or_create(
        session, callback.from_user.id, callback.from_user.username
    )
    text, keyboard = await _list_view(session, user_id)
    await _show(callback, text, keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("order:view:"))
async def show_detail(callback: CallbackQuery, session: AsyncSession) -> None:
    order_id = int(callback.data.split(":")[2])

    user_id = await user_service.get_or_create(
        session, callback.from_user.id, callback.from_user.username
    )
    # None covers both "gone" and "somebody else's" — nothing here tells them apart,
    # so the message is left untouched either way.
    order = await order_service.get_for_user(session, order_id, user_id)
    if order is None:
        await callback.answer(GONE, show_alert=True)
        return

    await _show(callback, _order_detail_text(order), _back_keyboard())
    await callback.answer()


async def _list_view(
    session: AsyncSession, user_id: int
) -> tuple[str, InlineKeyboardMarkup | None]:
    orders = await order_service.list_for_user(session, user_id)
    if not orders:
        return EMPTY, None

    rows = "\n".join(_summary(order) for order in orders)
    return f"{HEADER}\n\n{rows}", _list_keyboard(orders)


def _summary(order: Order) -> str:
    return (
        f"<b>#{order.id}</b> · {render.status_label(order.status)} · "
        f"{render.money(order.total_price)} · {_created(order)}"
    )


def _order_detail_text(order: Order) -> str:
    items = "\n".join(
        f"• <b>{_product_name(item)}</b> × {item.quantity} — "
        f"{render.money(item.price)} each"
        for item in order.items
    )
    return (
        f"📦 <b>Order #{order.id}</b>\n"
        f"Status: {render.status_label(order.status)}\n"
        f"Placed: {_created(order)}\n\n"
        f"{items}\n\n"
        f"<b>Total: {render.money(order.total_price)}</b>\n\n"
        f"📍 {order.address}"
    )


def _product_name(item) -> str:
    # Products are soft-deleted, so this normally resolves; the fallback keeps a
    # broken row from taking the whole card down.
    return item.product.name if item.product is not None else f"#{item.product_id}"


def _created(order: Order) -> str:
    # created_at is stored with a timezone and comes back as UTC. Said out loud, so a
    # customer reading a placement time does not have to guess the offset.
    return f"{order.created_at:%d.%m.%Y %H:%M} UTC"


def _list_keyboard(orders: list[Order]) -> InlineKeyboardMarkup:
    # Built here rather than in keyboards/: these buttons exist only for this router.
    b = InlineKeyboardBuilder()
    for order in orders:
        b.button(
            text=f"#{order.id} · {render.status_label(order.status)} · "
            f"{render.money(order.total_price)}",
            callback_data=f"order:view:{order.id}",
        )
    b.adjust(1)
    return b.as_markup()


def _back_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ Back", callback_data="order:mine")
    return b.as_markup()


async def _show(
    callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup | None
) -> None:
    """Render in place; fall back to a new message when the old one cannot be edited."""
    message = callback.message
    if not isinstance(message, Message):
        return

    try:
        await message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest:
        # Identical content, or a message too old to edit.
        await message.answer(text, reply_markup=keyboard)
