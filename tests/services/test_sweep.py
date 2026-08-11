"""The sweep job. TODO: fill in during implementation.

The whole reason the service test layer exists: sweep correctness is entirely
about time windows and status transitions in the database.
"""

import pytest

pytestmark = pytest.mark.asyncio


async def test_fresh_order_is_untouched(session):
    pytest.skip("TODO")


async def test_order_past_reminder_mark_is_warned_once(session):
    """Second pass must not warn again — that is what warning_sent is for."""
    pytest.skip("TODO")


async def test_order_past_cancel_mark_becomes_cancelled_unpaid(session):
    pytest.skip("TODO")


async def test_paid_order_is_never_cancelled(session):
    pytest.skip("TODO")


async def test_sweep_is_idempotent(session):
    """Running it twice in a row changes nothing the second time."""
    pytest.skip("TODO")


async def test_missed_window_still_caught_after_restart(session):
    """An order that came due while the process was down is handled on the next pass."""
    pytest.skip("TODO")
