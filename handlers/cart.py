"""Cart view and editing. TODO: fill in during implementation."""

from aiogram import Router

router = Router(name="cart")

# Handlers to implement: show cart, change quantity, remove line, clear cart.
#
# Showing the cart is always:
#     lines, problems, total = await cart_service.resolve(session, user.id)
#     if problems: await message.answer(render.problems_text(problems))
#     await message.answer(render.cart_text(lines, total))
