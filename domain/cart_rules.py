"""Cart validity rules — the single place `max_quantity` is interpreted.

v1 spread this across six sites with four different behaviours and three
different fallback defaults.
"""

from domain.models import CartLine, CartProblem, ProductView


def check(lines: list[CartLine]) -> list[CartProblem]:
    """Report every reason the cart cannot be ordered as-is.

    Reports facts only — it neither drops nor clamps anything. Use apply() for that.
    """
    problems: list[CartProblem] = []

    for line in lines:
        product = line.product

        if product is None or product.is_deleted:
            problems.append(
                CartProblem(
                    product_id=line.product_id,
                    kind="gone",
                    product_name=product.name if product else None,
                )
            )
            continue

        if not product.in_stock:
            problems.append(
                CartProblem(
                    product_id=line.product_id,
                    kind="out_of_stock",
                    product_name=product.name,
                )
            )
            continue

        if line.qty > product.max_quantity:
            problems.append(
                CartProblem(
                    product_id=line.product_id,
                    kind="over_max",
                    product_name=product.name,
                    allowed_qty=product.max_quantity,
                )
            )

    return problems


def apply(lines: list[CartLine]) -> list[CartLine]:
    """Return the cart with problems resolved: unavailable lines dropped, quantities clamped.

    Idempotent — apply(apply(x)) == apply(x), and check(apply(x)) == [].
    """
    resolved: list[CartLine] = []

    for line in lines:
        product = line.product

        if product is None or product.is_deleted or not product.in_stock:
            continue

        qty = min(line.qty, product.max_quantity)
        if qty <= 0:
            continue

        resolved.append(
            line if qty == line.qty else CartLine(line.product_id, qty, product)
        )

    return resolved


def allowed_to_add(line: CartLine | None, product: ProductView, qty_to_add: int) -> int:
    """How many units may actually be added, given what is already in the cart.

    v1's bug #6 lived here: both add paths validated as an *addition*
    (`in_cart + qty > max`) and then *overwrote* the quantity instead of adding.
    Callers add this return value to the existing quantity — never replace with it.
    """
    already = line.qty if line else 0
    room = product.max_quantity - already
    return max(0, min(qty_to_add, room))
