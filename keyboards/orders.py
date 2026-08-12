from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_payment_claim_keyboard(order_id: int) -> InlineKeyboardMarkup:
    """Customer-side button: "I have paid". Signals the admin, changes no status."""
    b = InlineKeyboardBuilder()
    b.button(text="✅ I have paid", callback_data=f"order:claim:{order_id}")
    return b.as_markup()


def get_admin_payment_keyboard(order_id: int) -> InlineKeyboardMarkup:
    """Admin-side confirm/reject.

    Sent from handlers/checkout.py; handled in handlers/admin/payments.py, where the
    IsAdmin filter applies. Never register these callbacks on a customer router.
    """
    b = InlineKeyboardBuilder()
    b.button(text="✅ Confirm payment", callback_data=f"pay:confirm:{order_id}")
    b.button(text="❌ Reject", callback_data=f"pay:reject:{order_id}")
    b.adjust(2)
    return b.as_markup()
