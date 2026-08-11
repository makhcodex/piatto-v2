"""Pure business rules.

Nothing in this package may import aiogram or sqlalchemy. Inputs and outputs
are plain values — no ORM rows, no Telegram objects, no I/O, no async.

The ban is enforced by tests/domain/test_no_framework_imports.py.
"""
