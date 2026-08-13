"""Admin surface. Authorisation is a property of belonging to this router.

Every admin-only handler lives under this package. The filters below are attached
once, to the router, so a handler cannot exist here without inheriting the check —
and cannot be authorised anywhere else.

This is the fix for v1's hole: admin_confirm_payment and admin_reject_payment were
registered on the *checkout* router (checkout.py:320, :360), where IsAdmin was never
attached and no inline check existed. Any user could confirm payment on any order.
"""

from aiogram import Router
from aiogram.filters import Filter
from aiogram.types import TelegramObject

from config import ADMIN_IDS


class IsAdmin(Filter):
    async def __call__(self, event: TelegramObject) -> bool:
        user = getattr(event, "from_user", None)
        return user is not None and user.id in ADMIN_IDS


router = Router(name="admin")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

from handlers.admin import catalogue, orders, payments  # noqa: E402

router.include_router(payments.router)
router.include_router(orders.router)
router.include_router(catalogue.router)
