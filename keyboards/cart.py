from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_cart_keyboard(lines) -> InlineKeyboardMarkup:
    """Per-line quantity controls plus cart-wide actions.

    The +/- buttons carry the resulting absolute quantity, not a delta, so the
    handler never does arithmetic — it parses a number and passes it to the service.
    """
    b = InlineKeyboardBuilder()

    for line in lines:
        product = line.product
        if product is None:
            continue

        b.button(text=f"{product.name} × {line.qty}", callback_data="cart:noop")

        if line.qty > 1:
            b.button(text="➖", callback_data=f"cart:set:{product.id}:{line.qty - 1}")
        else:
            b.button(text="·", callback_data="cart:noop")

        if line.qty < product.max_quantity:
            b.button(text="➕", callback_data=f"cart:set:{product.id}:{line.qty + 1}")
        else:
            b.button(text="·", callback_data="cart:noop")

        b.button(text="🗑", callback_data=f"cart:remove:{product.id}")

    b.button(text="📋 Catalogue", callback_data="back_to_categories")
    b.button(text="🗑 Clear cart", callback_data="cart:clear:prompt")

    b.adjust(*([4] * sum(1 for line in lines if line.product is not None)), 2)
    return b.as_markup()


def get_clear_confirm_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Yes, clear it", callback_data="cart:clear:yes")
    b.button(text="◀️ Keep it", callback_data="cart:view")
    b.adjust(2)
    return b.as_markup()
