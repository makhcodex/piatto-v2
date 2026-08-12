"""Checkout wizard and the customer side of payment.

Contains NO admin handlers. Payment confirmation and rejection live in
handlers/admin/payments.py, under the IsAdmin filter — sending the buttons happens
here, handling them does not.
"""

import logging
import re

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from config import ADMIN_IDS, CANCEL_MINUTES, PAYMENT_CARD_NUMBER
from handlers import render
from keyboards.main_menu import get_main_keyboard
from keyboards.orders import get_admin_payment_keyboard, get_payment_claim_keyboard
from services import cart_service, order_service, user_service

logger = logging.getLogger(__name__)

router = Router(name="checkout")

NAME_MIN, NAME_MAX = 2, 64
ADDRESS_MIN, ADDRESS_MAX = 5, 500
# Digits with the punctuation people actually type. Format only — not a business rule.
PHONE_ALLOWED = re.compile(r"^[+\d\s\-()]{7,20}$")
DIGITS = re.compile(r"\d")

ASK_NAME = "👤 What name should we put on the order?"
ASK_PHONE = "📞 Your phone number?"
ASK_ADDRESS = "📍 Delivery address? Include the house number."
CANCELLED = "Checkout cancelled. Your cart is untouched."
EMPTY_CART = "🛒 Your cart is empty — nothing to order yet."


class Checkout(StatesGroup):
    """Short-lived input state: which field is being entered, plus what was entered.

    Losing this mid-checkout costs the user a restart of the wizard. The cart is in
    cart_items and is unaffected.
    """

    waiting_for_name = State()
    waiting_for_phone = State()
    waiting_for_address = State()


def _admin_notification(order_id: int, name: str, phone: str, address: str, cart: str) -> str:
    return (
        f"🔔 <b>New order #{order_id}</b>\n\n"
        f"{cart}\n\n"
        f"👤 {name}\n"
        f"📞 {phone}\n"
        f"📍 {address}"
    )


def _customer_confirmation(order_id: int, total: str) -> str:
    card = PAYMENT_CARD_NUMBER or "(payment details not configured — contact us)"
    return (
        f"✅ <b>Order #{order_id} placed.</b>\n\n"
        f"Amount due: <b>{total}</b>\n"
        f"Transfer to: <code>{card}</code>\n\n"
        f"Tap the button below once you have paid. Unpaid orders are cancelled "
        f"automatically after {CANCEL_MINUTES} minutes."
    )


@router.message(F.text == "✅ Place Order")
async def start_checkout(message: Message, state: FSMContext, session: AsyncSession) -> None:
    user_id = await user_service.get_or_create(
        session, message.from_user.id, message.from_user.username
    )
    lines, problems, _ = await cart_service.resolve(session, user_id)

    if problems:
        await message.answer(render.problems_text(problems))
    if not lines:
        await message.answer(EMPTY_CART)
        return

    await state.set_state(Checkout.waiting_for_name)
    await message.answer(ASK_NAME)


@router.message(Command("cancel"), Checkout.waiting_for_name)
@router.message(Command("cancel"), Checkout.waiting_for_phone)
@router.message(Command("cancel"), Checkout.waiting_for_address)
async def cancel_checkout(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(CANCELLED, reply_markup=get_main_keyboard())


@router.message(Checkout.waiting_for_name)
async def step_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not NAME_MIN <= len(name) <= NAME_MAX:
        await message.answer(f"❌ Name must be {NAME_MIN}–{NAME_MAX} characters. Try again:")
        return

    await state.update_data(name=name)
    await state.set_state(Checkout.waiting_for_phone)
    await message.answer(ASK_PHONE)


@router.message(Checkout.waiting_for_phone)
async def step_phone(message: Message, state: FSMContext) -> None:
    phone = (message.text or "").strip()
    if not PHONE_ALLOWED.match(phone) or len(DIGITS.findall(phone)) < 7:
        await message.answer("❌ That does not look like a phone number. Try again:")
        return

    await state.update_data(phone=phone)
    await state.set_state(Checkout.waiting_for_address)
    await message.answer(ASK_ADDRESS)


@router.message(Checkout.waiting_for_address)
async def step_address(
    message: Message, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    address = (message.text or "").strip()
    if not ADDRESS_MIN <= len(address) <= ADDRESS_MAX:
        await message.answer(
            f"❌ Address must be {ADDRESS_MIN}–{ADDRESS_MAX} characters. Try again:"
        )
        return
    if not DIGITS.search(address):
        await message.answer("❌ Include the house number. Try again:")
        return

    data = await state.get_data()
    user_id = await user_service.get_or_create(
        session, message.from_user.id, message.from_user.username
    )

    # Snapshot the cart for the admin notification — create_order empties it.
    lines, problems, total = await cart_service.resolve(session, user_id)
    if problems:
        await state.clear()
        await message.answer(render.problems_text(problems))
        await message.answer("Your cart changed — review it and start checkout again.")
        return

    cart_summary = render.cart_text(lines, total)

    try:
        order = await order_service.create_order(session, user_id, address)
    except order_service.CartNotOrderable as exc:
        await state.clear()
        await message.answer(
            render.problems_text(exc.problems) if exc.problems else EMPTY_CART
        )
        return
    except order_service.RateLimitExceeded as exc:
        await state.clear()
        await message.answer(
            f"⏳ You have placed {exc.placed} orders in the last hour, which is the "
            f"limit of {exc.limit}. Try again later."
        )
        return

    await state.clear()
    await message.answer(
        _customer_confirmation(order.id, render.money(order.total_price)),
        reply_markup=get_payment_claim_keyboard(order.id),
    )

    await _notify_admins(
        bot,
        _admin_notification(
            order.id, data.get("name", "—"), data.get("phone", "—"), address, cart_summary
        ),
        get_admin_payment_keyboard(order.id),
    )


@router.callback_query(F.data.startswith("order:claim:"))
async def claim_payment(callback: CallbackQuery, bot: Bot) -> None:
    """The customer says they paid. A signal to the admin — no status change."""
    order_id = int(callback.data.split(":")[2])

    await callback.answer("Thanks — we are checking the transfer.")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass

    await _notify_admins(
        bot,
        f"💸 Customer claims order #{order_id} is paid. Verify the transfer.",
        get_admin_payment_keyboard(order_id),
    )


async def _notify_admins(bot: Bot, text: str, keyboard) -> None:
    """Best effort — a failed notification must never undo a committed order."""
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, reply_markup=keyboard)
        except TelegramAPIError as exc:
            logger.error("Admin notification to %s failed: %s", admin_id, exc)
