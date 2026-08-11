"""/start, main menu. TODO: fill in during implementation."""

from aiogram import Router

router = Router(name="start")

# Handlers to implement: /start -> user_service.get_or_create + main menu keyboard.
# No state juggling: the cart lives in cart_items, so state.clear() is safe anywhere.
