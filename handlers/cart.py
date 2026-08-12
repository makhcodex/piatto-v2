"""Cart viewing, editing and clearing.

Adding to the cart lives in handlers/menu.py; ordering lives in handlers/checkout.py.
"""

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from handlers import render
from keyboards.cart import get_cart_keyboard, get_clear_confirm_keyboard
from services import cart_service, user_service

logger = logging.getLogger(__name__)

router = Router(name="cart")

EMPTY = "🛒 Your cart is empty.\n\nTap 📋 Catalogue to add something."
CLEARED = "🗑 Cart cleared."
CLEAR_CONFIRM = "Remove everything from your cart?"


async def _load(session: AsyncSession, tg_user):
    """Resolve the cart and return (text, keyboard, problems_text_or_None)."""
    user_id = await user_service.get_or_create(session, tg_user.id, tg_user.username)
    lines, problems, total = await cart_service.resolve(session, user_id)

    if not lines:
        return EMPTY, None, render.problems_text(problems) if problems else None

    return (
        render.cart_text(lines, total),
        get_cart_keyboard(lines),
        render.problems_text(problems) if problems else None,
    )


async def _show(message: Message, session: AsyncSession, tg_user, edit: bool) -> None:
    """Render the cart, in place when the trigger was an inline button."""
    text, keyboard, problems = await _load(session, tg_user)

    if problems:
        await message.answer(problems)

    if edit:
        try:
            await message.edit_text(text, reply_markup=keyboard)
            return
        except TelegramBadRequest:
            # Nothing changed, or the message is too old to edit.
            pass

    await message.answer(text, reply_markup=keyboard)


@router.message(F.text == "🛒 Cart")
async def show_cart(message: Message, session: AsyncSession) -> None:
    await _show(message, session, message.from_user, edit=False)


@router.callback_query(F.data == "cart:view")
async def view_cart(callback: CallbackQuery, session: AsyncSession) -> None:
    await _show(callback.message, session, callback.from_user, edit=True)
    await callback.answer()


@router.callback_query(F.data == "cart:noop")
async def noop(callback: CallbackQuery) -> None:
    """Labels and disabled slots — acknowledge so the client stops spinning."""
    await callback.answer()


@router.callback_query(F.data.startswith("cart:set:"))
async def set_quantity(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, raw_product_id, raw_qty = callback.data.split(":")

    user_id = await user_service.get_or_create(
        session, callback.from_user.id, callback.from_user.username
    )
    problem = await cart_service.set_qty(
        session, user_id, int(raw_product_id), int(raw_qty)
    )

    await callback.answer(render.problem_text(problem) if problem else "", show_alert=bool(problem))
    await _show(callback.message, session, callback.from_user, edit=True)


@router.callback_query(F.data.startswith("cart:remove:"))
async def remove_line(callback: CallbackQuery, session: AsyncSession) -> None:
    product_id = int(callback.data.split(":")[2])

    user_id = await user_service.get_or_create(
        session, callback.from_user.id, callback.from_user.username
    )
    await cart_service.remove(session, user_id, product_id)

    await callback.answer("Removed.")
    await _show(callback.message, session, callback.from_user, edit=True)


@router.callback_query(F.data == "cart:clear:prompt")
async def clear_prompt(callback: CallbackQuery) -> None:
    try:
        await callback.message.edit_text(CLEAR_CONFIRM, reply_markup=get_clear_confirm_keyboard())
    except TelegramBadRequest:
        await callback.message.answer(CLEAR_CONFIRM, reply_markup=get_clear_confirm_keyboard())
    await callback.answer()


@router.callback_query(F.data == "cart:clear:yes")
async def clear_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    user_id = await user_service.get_or_create(
        session, callback.from_user.id, callback.from_user.username
    )
    await cart_service.clear(session, user_id)

    await callback.answer(CLEARED)
    try:
        await callback.message.edit_text(EMPTY)
    except TelegramBadRequest:
        await callback.message.answer(EMPTY)
