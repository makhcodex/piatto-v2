from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from db.models import Category, Product


def get_categories_keyboard(categories: list[Category]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for cat in categories:
        b.button(text=cat.name, callback_data=f"category:{cat.slug}")
    b.adjust(1)
    return b.as_markup()


def get_items_keyboard(products: list[Product]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for p in products:
        # Two decimals: int() truncated 1.99€ to 1€ in v1.
        b.button(text=f"{p.name} — {p.price:.2f}€", callback_data=f"item:{p.id}")
    b.button(text="◀️ Back to Categories", callback_data="back_to_categories")
    b.adjust(1)
    return b.as_markup()


def get_quantity_keyboard(product_id: int, max_quantity: int) -> InlineKeyboardMarkup:
    """Quick quantity buttons for adding a product to the cart."""
    b = InlineKeyboardBuilder()
    quick = min(4, max_quantity)
    for qty in range(1, quick + 1):
        b.button(text=str(qty), callback_data=f"qty:quick:{product_id}:{qty}")
    b.button(text="✏️ Custom amount", callback_data=f"qty:custom:{product_id}")
    b.button(text="❌ Cancel", callback_data="qty:cancel")
    b.adjust(quick, 2)
    return b.as_markup()
