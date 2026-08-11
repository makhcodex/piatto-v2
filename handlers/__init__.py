"""Router registry.

Order matters: the admin router is included first so admin callbacks resolve
under IsAdmin before any customer router can see them.
"""

from aiogram import Router

from handlers import cart, checkout, menu, start
from handlers import admin


def build_router() -> Router:
    root = Router(name="root")
    root.include_router(admin.router)
    root.include_router(start.router)
    root.include_router(menu.router)
    root.include_router(cart.router)
    root.include_router(checkout.router)
    return root
