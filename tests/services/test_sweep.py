"""The sweep job, against a real Postgres.

The whole reason the service test layer exists: sweep correctness is entirely
about time windows and status transitions in the database.

Ages are given in minutes relative to now and chosen far from the WARNING_MINUTES /
CANCEL_MINUTES marks, so the suite does not flip when the configured window changes.
One boundary test reads the config values on purpose.

Only the bot is a stand-in — Telegram is the one dependency a test may not have.
The database is piatto_test, and run_once reaches it through the test's own session
(see the sweep_session fixture).
"""

import pytest

from config import ADMIN_IDS, CANCEL_MINUTES, WARNING_MINUTES
from db.models import Order, OrderStatus, User
from services import sweep

pytestmark = pytest.mark.asyncio

# Comfortably inside each window, whatever the configured minutes are.
FRESH = 0
DUE_FOR_WARNING = (WARNING_MINUTES + CANCEL_MINUTES) / 2
OVERDUE = CANCEL_MINUTES + 60


async def _reread(session, order: Order) -> Order:
    """Read the row back from Postgres, not from the identity map."""
    session.expunge_all()
    return await session.get(Order, order.id)


# ── orders_pending_warning ────────────────────────────────────────────────────


async def test_pending_warning_picks_the_order_past_the_reminder_mark(
    session, user, make_order
):
    due = await make_order(user, minutes_ago=DUE_FOR_WARNING)

    found = await sweep.orders_pending_warning(session)

    assert [o.id for o in found] == [due.id]


async def test_pending_warning_skips_a_fresh_order(session, user, make_order):
    await make_order(user, minutes_ago=FRESH)

    assert await sweep.orders_pending_warning(session) == []


async def test_pending_warning_skips_an_already_warned_order(session, user, make_order):
    await make_order(user, minutes_ago=DUE_FOR_WARNING, warning_sent=True)

    assert await sweep.orders_pending_warning(session) == []


@pytest.mark.parametrize(
    "status",
    [OrderStatus.PAID, OrderStatus.PREPARING, OrderStatus.DELIVERED, OrderStatus.CANCELLED_UNPAID],
)
async def test_pending_warning_skips_orders_that_are_not_pending(
    session, user, make_order, status
):
    await make_order(user, minutes_ago=DUE_FOR_WARNING, status=status)

    assert await sweep.orders_pending_warning(session) == []


async def test_pending_warning_boundary_is_warning_minutes(session, user, make_order):
    """Just short of the mark is left alone; just past it is picked up."""
    await make_order(user, minutes_ago=WARNING_MINUTES - 0.5)
    just_past = await make_order(user, minutes_ago=WARNING_MINUTES + 0.5)

    found = await sweep.orders_pending_warning(session)

    assert [o.id for o in found] == [just_past.id]


# ── orders_to_auto_cancel ─────────────────────────────────────────────────────


async def test_auto_cancel_picks_the_order_past_the_cancel_mark(session, user, make_order):
    overdue = await make_order(user, minutes_ago=OVERDUE)

    found = await sweep.orders_to_auto_cancel(session)

    assert [o.id for o in found] == [overdue.id]


async def test_auto_cancel_skips_a_fresh_order(session, user, make_order):
    await make_order(user, minutes_ago=FRESH)
    await make_order(user, minutes_ago=DUE_FOR_WARNING)

    assert await sweep.orders_to_auto_cancel(session) == []


@pytest.mark.parametrize(
    "status",
    [OrderStatus.PAID, OrderStatus.PREPARING, OrderStatus.DELIVERED, OrderStatus.CANCELLED_UNPAID],
)
async def test_auto_cancel_skips_orders_that_are_not_pending(session, user, make_order, status):
    await make_order(user, minutes_ago=OVERDUE, status=status)

    assert await sweep.orders_to_auto_cancel(session) == []


async def test_auto_cancel_boundary_is_cancel_minutes(session, user, make_order):
    await make_order(user, minutes_ago=CANCEL_MINUTES - 0.5)
    just_past = await make_order(user, minutes_ago=CANCEL_MINUTES + 0.5)

    found = await sweep.orders_to_auto_cancel(session)

    assert [o.id for o in found] == [just_past.id]


# ── run_once ──────────────────────────────────────────────────────────────────


async def test_fresh_order_is_untouched(sweep_session, user, make_order, bot):
    order = await make_order(user, minutes_ago=FRESH)

    await sweep.run_once(bot)

    reread = await _reread(sweep_session, order)
    assert reread.status == OrderStatus.PENDING
    assert reread.warning_sent is False
    assert bot.sent == []


async def test_order_past_reminder_mark_is_warned_once(sweep_session, user, make_order, bot):
    """Second pass must not warn again — that is what warning_sent is for."""
    order = await make_order(user, minutes_ago=DUE_FOR_WARNING)
    telegram_id = (await sweep_session.get(User, user)).telegram_id

    await sweep.run_once(bot)

    reread = await _reread(sweep_session, order)
    assert reread.warning_sent is True
    assert reread.status == OrderStatus.PENDING, "a reminder must not change the status"
    assert len(bot.to(telegram_id)) == 1
    assert f"#{order.id}" in bot.to(telegram_id)[0]

    await sweep.run_once(bot)

    assert len(bot.to(telegram_id)) == 1


async def test_order_past_cancel_mark_becomes_cancelled_unpaid(
    sweep_session, user, make_order, bot
):
    order = await make_order(user, minutes_ago=OVERDUE)
    telegram_id = (await sweep_session.get(User, user)).telegram_id

    await sweep.run_once(bot)

    reread = await _reread(sweep_session, order)
    assert reread.status == OrderStatus.CANCELLED_UNPAID
    assert len(bot.to(telegram_id)) == 1
    assert f"#{order.id}" in bot.to(telegram_id)[0]
    # The admins hear about it too.
    for admin_id in ADMIN_IDS:
        assert len(bot.to(admin_id)) == 1


async def test_paid_order_is_never_cancelled(sweep_session, user, make_order, bot):
    order = await make_order(user, minutes_ago=OVERDUE, status=OrderStatus.PAID)

    await sweep.run_once(bot)

    assert (await _reread(sweep_session, order)).status == OrderStatus.PAID
    assert bot.sent == []


async def test_one_pass_warns_and_cancels_the_right_orders(
    sweep_session, user, other_user, make_order, bot
):
    fresh = await make_order(user, minutes_ago=FRESH)
    due = await make_order(user, minutes_ago=DUE_FOR_WARNING)
    overdue = await make_order(other_user, minutes_ago=OVERDUE)

    await sweep.run_once(bot)

    sweep_session.expunge_all()
    assert (await sweep_session.get(Order, fresh.id)).status == OrderStatus.PENDING
    assert (await sweep_session.get(Order, fresh.id)).warning_sent is False
    assert (await sweep_session.get(Order, due.id)).warning_sent is True
    assert (await sweep_session.get(Order, due.id)).status == OrderStatus.PENDING
    assert (await sweep_session.get(Order, overdue.id)).status == OrderStatus.CANCELLED_UNPAID


# ── commit first, notify second ───────────────────────────────────────────────


async def test_warning_survives_a_failing_notification(
    sweep_session, user, make_order, failing_bot
):
    """The flag is committed before Telegram is told; an outage must not undo it."""
    order = await make_order(user, minutes_ago=DUE_FOR_WARNING)

    await sweep.run_once(failing_bot)

    assert (await _reread(sweep_session, order)).warning_sent is True
    assert failing_bot.sent, "the sweep never even tried to notify"


async def test_auto_cancel_survives_a_failing_notification(
    sweep_session, user, make_order, failing_bot
):
    order = await make_order(user, minutes_ago=OVERDUE)

    await sweep.run_once(failing_bot)

    assert (await _reread(sweep_session, order)).status == OrderStatus.CANCELLED_UNPAID


async def test_a_failing_notification_does_not_abort_the_pass(
    sweep_session, user, other_user, make_order, failing_bot
):
    """One dead chat must not stop the orders behind it from being cancelled."""
    first = await make_order(user, minutes_ago=OVERDUE)
    second = await make_order(other_user, minutes_ago=OVERDUE)

    await sweep.run_once(failing_bot)

    sweep_session.expunge_all()
    assert (await sweep_session.get(Order, first.id)).status == OrderStatus.CANCELLED_UNPAID
    assert (await sweep_session.get(Order, second.id)).status == OrderStatus.CANCELLED_UNPAID


# ── idempotence and restarts ──────────────────────────────────────────────────


async def test_sweep_is_idempotent(sweep_session, user, other_user, make_order, bot):
    """Running it twice in a row changes nothing the second time."""
    due = await make_order(user, minutes_ago=DUE_FOR_WARNING)
    overdue = await make_order(other_user, minutes_ago=OVERDUE)

    await sweep.run_once(bot)
    after_first = list(bot.sent)

    await sweep.run_once(bot)

    assert bot.sent == after_first, "the second pass sent something again"
    sweep_session.expunge_all()
    assert (await sweep_session.get(Order, due.id)).warning_sent is True
    assert (await sweep_session.get(Order, overdue.id)).status == OrderStatus.CANCELLED_UNPAID


async def test_missed_window_still_caught_after_restart(sweep_session, user, make_order, bot):
    """An order that came due while the process was down is handled on the next pass."""
    # Nothing ran while this one aged straight past both marks.
    order = await make_order(user, minutes_ago=OVERDUE)

    await sweep.run_once(bot)

    assert (await _reread(sweep_session, order)).status == OrderStatus.CANCELLED_UNPAID
