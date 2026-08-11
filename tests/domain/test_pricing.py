from decimal import Decimal

from domain import pricing
from domain.models import CartLine, ProductView


def product(price: str, **kw) -> ProductView:
    return ProductView(
        id=kw.get("id", 1),
        name=kw.get("name", "Pizza"),
        unit_price=Decimal(price),
        max_quantity=kw.get("max_quantity", 10),
        in_stock=kw.get("in_stock", True),
        is_deleted=kw.get("is_deleted", False),
    )


def test_empty_cart_totals_zero():
    assert pricing.cart_total([]) == Decimal("0.00")


def test_single_line():
    lines = [CartLine(1, 3, product("12.50"))]
    assert pricing.cart_total(lines) == Decimal("37.50")


def test_multiple_lines():
    lines = [
        CartLine(1, 2, product("12.50", id=1)),
        CartLine(2, 1, product("8.25", id=2)),
    ]
    assert pricing.cart_total(lines) == Decimal("33.25")


def test_missing_product_contributes_nothing():
    lines = [CartLine(1, 2, product("10.00")), CartLine(99, 5, None)]
    assert pricing.cart_total(lines) == Decimal("20.00")


def test_total_is_decimal_not_float():
    total = pricing.cart_total([CartLine(1, 1, product("0.10"))])
    assert isinstance(total, Decimal)


def test_no_binary_float_drift():
    """0.1 * 3 is 0.30000000000000004 in float. This is why money is Decimal."""
    lines = [CartLine(1, 3, product("0.10"))]
    assert pricing.cart_total(lines) == Decimal("0.30")
