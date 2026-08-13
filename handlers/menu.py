"""Catalogue browsing and adding to the cart.

Cart viewing and editing live in handlers/cart.py. This module only puts things in.
"""

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from handlers import render
from keyboards.catalog import (
    get_categories_keyboard, get_items_keyboard, get_quantity_keyboard,
)
from keyboards.main_menu import MENU_TEXTS
from services import cart_service, category_service, product_service, user_service

logger = logging.getLogger(__name__)

router = Router(name="menu")

CHOOSE_CATEGORY = "Choose a category:"
CAPTION_LIMIT = 1024


class MenuStates(StatesGroup):
    """One transient step: the user is typing a custom quantity.

    `pending_product_id` in state data says which product it is for. Losing it on a
    restart costs one re-tap of the product; the cart is in Postgres and is unaffected.
    """

    waiting_for_quantity = State()


async def _send_categories(message: Message, session: AsyncSession) -> None:
    categories = await category_service.list_all(session)
    if not categories:
        await message.answer("The menu is empty right now.")
        return
    await message.answer(CHOOSE_CATEGORY, reply_markup=get_categories_keyboard(categories))


def _product_caption(product) -> str:
    description = f"\n{product.description}\n" if product.description else ""
    return (
        f"🍕 <b>{product.name}</b>\n"
        f"{description}\n"
        f"💰 Price: <b>{render.money(product.price)}</b>\n"
        f"📦 Max per order: {product.max_quantity}\n\n"
        "Choose quantity:"
    )


async def _add_to_cart(
    session: AsyncSession, tg_user, product_id: int, qty: int
) -> tuple[int, str]:
    """Add to cart and return (added, message for the user)."""
    user_id = await user_service.get_or_create(session, tg_user.id, tg_user.username)
    added, problem = await cart_service.add(session, user_id, product_id, qty)

    if problem is not None:
        return 0, render.problem_text(problem)
    if added < qty:
        return added, f"⚠️ Only {added} added — that is the limit for this item."
    return added, f"✅ Added {added} to your cart."


@router.message(F.text == "📋 Catalogue")
async def show_catalogue(message: Message, session: AsyncSession) -> None:
    await _send_categories(message, session)


@router.callback_query(F.data == "back_to_categories")
async def back_to_categories(callback: CallbackQuery, session: AsyncSession) -> None:
    categories = await category_service.list_all(session)
    keyboard = get_categories_keyboard(categories)
    try:
        await callback.message.edit_text(CHOOSE_CATEGORY, reply_markup=keyboard)
    except TelegramBadRequest:
        # The previous message was a photo, which cannot be edited into text.
        await callback.message.answer(CHOOSE_CATEGORY, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("category:"))
async def show_category_items(callback: CallbackQuery, session: AsyncSession) -> None:
    slug = callback.data.split(":", 1)[1]
    category = await category_service.get_by_slug(session, slug)
    if category is None or category.is_deleted:
        await callback.answer("This category is gone.", show_alert=True)
        return

    products = await product_service.list_by_category(session, category.id)
    if not products:
        await callback.answer("Nothing in this category yet.", show_alert=True)
        return

    text = f"{category.name}\n\nPick an item:"
    keyboard = get_items_keyboard(products)
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("item:"))
async def select_item(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    product_id = int(callback.data.split(":", 1)[1])
    product = await product_service.get(session, product_id)

    if product is None:
        await callback.answer("This item is no longer available.", show_alert=True)
        return
    if not product.in_stock:
        await callback.answer("Out of stock.", show_alert=True)
        return

    caption = _product_caption(product)
    keyboard = get_quantity_keyboard(product.id, product.max_quantity)

    # A caption past the limit is not a photo any more — it would arrive truncated,
    # so the whole card falls through to the text branch instead.
    if product.image_url and len(caption) <= CAPTION_LIMIT:
        try:
            await bot.send_photo(
                callback.message.chat.id,
                product.image_url,
                caption=caption,
                reply_markup=keyboard,
            )
            await callback.answer()
            return
        except TelegramAPIError as exc:
            # A broken image_url must not hide the product — same fallback as the
            # optional logo in start._greet. Every API failure counts, not just 400:
            # a fetch timeout arrives as TelegramNetworkError.
            logger.warning("Photo failed for product %d (%s): %s",
                           product.id, product.image_url, exc)

    await callback.message.answer(caption, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("qty:quick:"))
async def quick_quantity(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, raw_product_id, raw_qty = callback.data.split(":")
    added, text = await _add_to_cart(
        session, callback.from_user, int(raw_product_id), int(raw_qty)
    )

    await callback.answer(text, show_alert=added == 0)
    if added:
        await callback.message.answer(text)


@router.callback_query(F.data.startswith("qty:custom:"))
async def custom_quantity_prompt(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    product_id = int(callback.data.split(":")[2])
    product = await product_service.get(session, product_id)

    if product is None or not product.in_stock:
        await callback.answer("This item is no longer available.", show_alert=True)
        return

    await state.set_state(MenuStates.waiting_for_quantity)
    await state.update_data(pending_product_id=product_id)
    await callback.answer()
    await callback.message.answer(
        f"✏️ How many <b>{product.name}</b>? Enter a number from 1 to "
        f"{product.max_quantity}, or /restart to abort."
    )


@router.callback_query(F.data == "qty:cancel")
async def cancel_quantity(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await state.clear()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    await callback.answer("Cancelled.")
    await _send_categories(callback.message, session)


@router.message(MenuStates.waiting_for_quantity, ~F.text.in_(MENU_TEXTS))
async def handle_custom_quantity(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) < 1:
        await message.answer("❌ Enter a whole number of 1 or more:")
        return

    data = await state.get_data()
    product_id = data.get("pending_product_id")
    if product_id is None:
        await state.clear()
        await message.answer("Something went stale — pick the item again.")
        await _send_categories(message, session)
        return

    await state.clear()
    _, text = await _add_to_cart(session, message.from_user, product_id, int(raw))
    await message.answer(text)
