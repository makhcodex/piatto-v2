"""Manual payment confirmation and rejection.

Lives here, not in checkout.py — see handlers/admin/__init__.py for why.

TODO: fill in during implementation.
"""

from aiogram import Router

router = Router(name="admin.payments")

# Handlers to implement:
#   confirm_payment(callback, callback_data, session, bot)
#       -> order_service.set_status(..., OrderStatus.PAID), notify buyer
#   reject_payment(callback, callback_data, session, bot)
#       -> notify buyer, leave order PENDING so the sweep can still cancel it
