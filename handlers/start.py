"""/start and /restart — onboarding and a clean slate."""

import logging
import os

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession

from config import LOGO_URL
from keyboards.main_menu import get_main_keyboard
from services import user_service

logger = logging.getLogger(__name__)

router = Router(name="start")

# Static text, no domain data — it stays here rather than in render.py, which exists
# for turning domain facts into text.
WELCOME = (
    "👋 <b>Welcome to Piatto!</b>\n"
    "🍕 Authentic Italian cuisine delivered to your door\n\n"
    "• 📋 <b>Catalogue</b> — browse our menu\n"
    "• 🛒 <b>Cart</b> — your current order\n"
    "• ✅ <b>Place Order</b> — checkout\n"
    "• 📦 <b>My Orders</b> — order history"
)

RESTARTED = "🔄 Starting fresh. Your cart is untouched."


async def _greet(message: Message, session: AsyncSession, prefix: str = "") -> None:
    """Register the user and show the welcome screen.

    The logo is optional branding: if LOGO_URL is unset or Telegram cannot fetch it,
    the text greeting still goes out. LOGO_URL may be a local path, a URL, or a file_id —
    a local path is uploaded, anything else is passed through as a string.
    """
    await user_service.get_or_create(
        session, message.from_user.id, message.from_user.username
    )

    text = f"{prefix}\n\n{WELCOME}" if prefix else WELCOME
    keyboard = get_main_keyboard()

    if LOGO_URL:
        photo = FSInputFile(LOGO_URL) if os.path.isfile(LOGO_URL) else LOGO_URL
        try:
            await message.answer_photo(photo, caption=text, reply_markup=keyboard)
            return
        except TelegramAPIError as exc:
            # Branding must not block onboarding — fall through to plain text.
            logger.warning("Logo send failed for %s: %s", LOGO_URL, exc)

    await message.answer(text, reply_markup=keyboard)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await _greet(message, session)


@router.message(Command("restart"))
async def cmd_restart(message: Message, state: FSMContext, session: AsyncSession) -> None:
    # Clears the checkout wizard only. The cart lives in cart_items and survives.
    await state.clear()
    await _greet(message, session, prefix=RESTARTED)
