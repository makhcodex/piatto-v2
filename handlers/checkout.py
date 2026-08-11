"""Checkout wizard and the customer side of payment. TODO: fill in during implementation.

Contains NO admin handlers. Payment confirmation and rejection live in
handlers/admin/payments.py, under the IsAdmin filter.
"""

from aiogram import Router
from aiogram.fsm.state import State, StatesGroup

router = Router(name="checkout")


class Checkout(StatesGroup):
    """The only thing FSM still holds: which wizard field is being entered.

    Losing this on restart costs the user one re-entry. The cart is in the
    database and is unaffected.
    """

    name = State()
    phone = State()
    address = State()


# Handlers to implement: wizard steps, order confirmation
# (order_service.create_order, catching CartNotOrderable), "I have paid" button
# notifying ADMIN_IDS, customer-side order status view.
