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


def get_orders_list_keyboard(rows: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    """Admin-side list: one button per order, (order_id, label) as given.

    The caller builds the labels. Keyboards know no status vocabulary and import
    nothing — that is why the status text arrives already rendered.
    """
    b = InlineKeyboardBuilder()
    for order_id, label in rows:
        b.button(text=label, callback_data=f"order:detail:{order_id}")
    b.adjust(1)
    return b.as_markup()


def get_order_detail_keyboard(order_id: int, next_label: str | None) -> InlineKeyboardMarkup:
    """Advance-to-next plus back-to-list. No advance button on a terminal status."""
    b = InlineKeyboardBuilder()
    if next_label is not None:
        b.button(
            text=f"➡️ Следующий статус → {next_label}",
            callback_data=f"order:advance:{order_id}",
        )
    b.button(text="◀️ Назад к списку", callback_data="order:list")
    b.adjust(1)
    return b.as_markup()
