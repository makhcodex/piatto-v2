"""Order browsing and status advancement. TODO: fill in during implementation."""

from aiogram import Router

router = Router(name="admin.orders")

# Handlers to implement: list active orders, view one, advance status
# via order_service.advance_status (transitions defined in db/models.NEXT_STATUS).
