"""Domain facts -> user-facing text.

All emoji and HTML in the cart flow live here. domain/ returns CartProblem
objects; this module is the only thing that knows how to say them out loud.

v1 did the opposite — validate_cart returned emoji HTML straight out of the
service layer (order_service.py:50-71), which made the rules unusable anywhere
a different wording was needed.
"""

from decimal import Decimal

from domain.models import CartLine, CartProblem


def problem_text(problem: CartProblem) -> str:
    name = problem.product_name or f"Item #{problem.product_id}"

    match problem.kind:
        case "gone":
            return f"❌ <b>{name}</b> is no longer available and was removed."
        case "out_of_stock":
            return f"❌ <b>{name}</b> is out of stock and was removed."
        case "over_max":
            return f"⚠️ Maximum for <b>{name}</b> is {problem.allowed_qty}. Reduced."

    return f"⚠️ <b>{name}</b> could not be added."


def problems_text(problems: list[CartProblem]) -> str:
    return "\n".join(problem_text(p) for p in problems)


def money(amount: Decimal) -> str:
    return f"{amount:.2f}€"


def cart_text(lines: list[CartLine], total: Decimal) -> str:
    if not lines:
        return "🛒 Your cart is empty."

    rows = [
        f"• <b>{line.product.name}</b> × {line.qty} — "
        f"{money(line.product.unit_price * line.qty)}"
        for line in lines
        if line.product is not None
    ]
    return "🛒 <b>Your cart</b>\n\n" + "\n".join(rows) + f"\n\n<b>Total: {money(total)}</b>"
