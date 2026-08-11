"""Cart persistence against a real Postgres. TODO: fill in during implementation.

Unit tests cannot reach these: the UNIQUE(user_id, product_id) constraint,
Numeric(10,2) round-tripping, and cascade deletes are database behaviour.
"""

import pytest

pytestmark = pytest.mark.asyncio


async def test_add_creates_row(session):
    pytest.skip("TODO")


async def test_add_accumulates_instead_of_overwriting(session):
    """The regression guard for v1 bug #6, at the persistence level."""
    pytest.skip("TODO")


async def test_add_is_capped_at_max_quantity(session):
    pytest.skip("TODO")


async def test_unique_constraint_prevents_duplicate_lines(session):
    pytest.skip("TODO")


async def test_resolve_drops_deleted_product_and_reports_it(session):
    pytest.skip("TODO")


async def test_resolve_clamps_and_persists_the_clamp(session):
    pytest.skip("TODO")


async def test_price_read_live_not_snapshotted(session):
    """Changing products.price changes the cart total — there is no stored price."""
    pytest.skip("TODO")


async def test_decimal_survives_round_trip(session):
    pytest.skip("TODO")
