"""Money arithmetic. Decimal only — float never touches a price.

v1 had three separate total implementations: two in float (menu.py, checkout.py)
and one in Decimal (order_service.py), so the displayed total and the stored
total were computed in different numeric modes.
"""

from decimal import Decimal

from domain.models import CartLine

ZERO = Decimal("0.00")


def line_total(line: CartLine) -> Decimal:
    """Price for one cart line. Lines with no product contribute nothing."""
    if line.product is None:
        return ZERO
    return line.product.unit_price * line.qty


def cart_total(lines: list[CartLine]) -> Decimal:
    """Sum of the cart.

    Expects already-resolved lines (see cart_rules.apply) — it prices what it is
    given and does not enforce limits.
    """
    return sum((line_total(line) for line in lines), ZERO)
