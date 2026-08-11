"""Catalogue browsing and adding to cart. TODO: fill in during implementation."""

from aiogram import Router

router = Router(name="menu")

# Handlers to implement: category list, product list, product card,
# quick-quantity buttons, custom quantity input.
#
# Adding to cart is always:
#     added, problem = await cart_service.add(session, user.id, product_id, qty)
#     if problem: await callback.answer(render.problem_text(problem), show_alert=True)
#
# Never compute a total here and never open a session — call the service.
