"""FSM states for the catalogue admin wizards.

Ten states in four groups — too many to keep readable inside catalogue.py. Each state
carries only the step; the accompanying data is the id being edited and the fields
already typed. Never a whole product: losing this on a restart must cost a retype,
not a corrupted row.
"""

from aiogram.fsm.state import State, StatesGroup


class AddProduct(StatesGroup):
    waiting_for_name = State()
    waiting_for_description = State()
    waiting_for_price = State()
    waiting_for_category = State()
    waiting_for_max_quantity = State()


class EditProduct(StatesGroup):
    waiting_for_price = State()
    waiting_for_max_quantity = State()


class AddCategory(StatesGroup):
    waiting_for_slug = State()
    waiting_for_name = State()


class EditCategory(StatesGroup):
    waiting_for_name = State()
