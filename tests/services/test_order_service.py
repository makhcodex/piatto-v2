"""Order creation against a real Postgres. TODO: fill in during implementation."""

import pytest

pytestmark = pytest.mark.asyncio


async def test_create_order_snapshots_price_into_order_items(session):
    """order_items.price must not follow later changes to products.price."""
    pytest.skip("TODO")


async def test_create_order_empties_the_cart(session):
    pytest.skip("TODO")


async def test_cart_and_order_are_one_transaction(session):
    """If item insertion fails, the order must not exist and the cart must survive."""
    pytest.skip("TODO")


async def test_create_order_rejects_a_cart_that_went_stale(session):
    pytest.skip("TODO")


async def test_total_matches_sum_of_order_items(session):
    pytest.skip("TODO")


async def test_rate_limit_blocks_the_sixth_order_in_an_hour(session):
    pytest.skip("TODO")
