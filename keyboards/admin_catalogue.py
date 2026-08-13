"""Admin menu-management keyboards.

Named admin_catalogue to keep a letter of distance from keyboards/catalog.py, which
is the customer-facing one. This module imports nothing — not services, not models.
Callers pass primitives, so a keyboard can never trigger a lazy load.
"""

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def _mark(is_deleted: bool, in_stock: bool | None = None) -> str:
    if is_deleted:
        return "🚫"
    if in_stock is False:
        return "❌"
    return "✅"


def get_products_keyboard(rows: list[tuple[int, str, bool, bool]]) -> InlineKeyboardMarkup:
    """One button per product: (product_id, name, in_stock, is_deleted)."""
    b = InlineKeyboardBuilder()
    for product_id, name, in_stock, is_deleted in rows:
        b.button(
            text=f"{_mark(is_deleted, in_stock)} {name}",
            callback_data=f"prod:detail:{product_id}",
        )
    b.button(text="➕ Добавить товар", callback_data="prod:add")
    b.button(text="📂 Категории", callback_data="ctg:list")
    b.adjust(*([1] * len(rows)), 2)
    return b.as_markup()


def get_product_detail_keyboard(
    product_id: int, in_stock: bool, is_deleted: bool
) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(
        text="❌ Убрать из наличия" if in_stock else "✅ Вернуть в наличие",
        callback_data=f"prod:stock:{product_id}",
    )
    b.button(
        text="♻️ Восстановить" if is_deleted else "🗑 Удалить",
        callback_data=f"prod:del:{product_id}",
    )
    b.button(text="💰 Цена", callback_data=f"prod:price:{product_id}")
    b.button(text="📦 Макс. количество", callback_data=f"prod:qty:{product_id}")
    b.button(text="◀️ К списку товаров", callback_data="prod:list")
    b.adjust(2, 2, 1)
    return b.as_markup()


def get_categories_keyboard(rows: list[tuple[int, str, bool]]) -> InlineKeyboardMarkup:
    """One button per category: (category_id, name, is_deleted)."""
    b = InlineKeyboardBuilder()
    for category_id, name, is_deleted in rows:
        b.button(
            text=f"{_mark(is_deleted)} {name}",
            callback_data=f"ctg:detail:{category_id}",
        )
    b.button(text="➕ Добавить категорию", callback_data="ctg:add")
    b.button(text="📦 Товары", callback_data="prod:list")
    b.adjust(*([1] * len(rows)), 2)
    return b.as_markup()


def get_category_detail_keyboard(category_id: int, is_deleted: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✏️ Переименовать", callback_data=f"ctg:rename:{category_id}")
    b.button(
        text="♻️ Восстановить" if is_deleted else "🗑 Скрыть",
        callback_data=f"ctg:del:{category_id}",
    )
    b.button(text="◀️ К списку категорий", callback_data="ctg:list")
    b.adjust(2, 1)
    return b.as_markup()


def get_category_pick_keyboard(rows: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    """Category choice inside the add-product wizard: (category_id, name)."""
    b = InlineKeyboardBuilder()
    for category_id, name in rows:
        b.button(text=name, callback_data=f"prod:setcat:{category_id}")
    b.adjust(1)
    return b.as_markup()
