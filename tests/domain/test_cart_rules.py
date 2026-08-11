from decimal import Decimal

from domain import cart_rules
from domain.models import CartLine, ProductView


def product(**kw) -> ProductView:
    return ProductView(
        id=kw.get("id", 1),
        name=kw.get("name", "Pizza"),
        unit_price=Decimal(kw.get("unit_price", "10.00")),
        max_quantity=kw.get("max_quantity", 5),
        in_stock=kw.get("in_stock", True),
        is_deleted=kw.get("is_deleted", False),
    )


class TestCheck:
    def test_clean_cart_has_no_problems(self):
        assert cart_rules.check([CartLine(1, 2, product())]) == []

    def test_missing_product_is_gone(self):
        (problem,) = cart_rules.check([CartLine(99, 1, None)])
        assert problem.kind == "gone"
        assert problem.product_id == 99

    def test_deleted_product_is_gone(self):
        (problem,) = cart_rules.check([CartLine(1, 1, product(is_deleted=True))])
        assert problem.kind == "gone"

    def test_out_of_stock(self):
        (problem,) = cart_rules.check([CartLine(1, 1, product(in_stock=False))])
        assert problem.kind == "out_of_stock"

    def test_over_max_reports_allowed_quantity(self):
        (problem,) = cart_rules.check([CartLine(1, 9, product(max_quantity=5))])
        assert problem.kind == "over_max"
        assert problem.allowed_qty == 5

    def test_exactly_at_max_is_fine(self):
        assert cart_rules.check([CartLine(1, 5, product(max_quantity=5))]) == []

    def test_one_problem_per_line(self):
        """A gone product is not also reported as out of stock."""
        problems = cart_rules.check([CartLine(1, 99, product(is_deleted=True))])
        assert len(problems) == 1

    def test_check_does_not_mutate_input(self):
        """v1's validate_cart mutated the caller's dict in place."""
        line = CartLine(1, 9, product(max_quantity=5))
        cart_rules.check([line])
        assert line.qty == 9

    def test_problems_carry_no_display_text(self):
        """Rules return facts. Rendering belongs to handlers."""
        (problem,) = cart_rules.check([CartLine(1, 9, product(max_quantity=5))])
        assert "⚠️" not in str(problem.product_name or "")


class TestApply:
    def test_drops_gone_and_out_of_stock(self):
        lines = [
            CartLine(1, 1, product(id=1)),
            CartLine(2, 1, product(id=2, is_deleted=True)),
            CartLine(3, 1, product(id=3, in_stock=False)),
            CartLine(4, 1, None),
        ]
        assert [line.product_id for line in cart_rules.apply(lines)] == [1]

    def test_clamps_to_max(self):
        (line,) = cart_rules.apply([CartLine(1, 99, product(max_quantity=5))])
        assert line.qty == 5

    def test_idempotent(self):
        lines = [CartLine(1, 99, product(max_quantity=5)), CartLine(2, 1, None)]
        once = cart_rules.apply(lines)
        assert cart_rules.apply(once) == once

    def test_result_is_always_clean(self):
        lines = [
            CartLine(1, 99, product(id=1, max_quantity=5)),
            CartLine(2, 1, product(id=2, in_stock=False)),
            CartLine(3, 1, None),
        ]
        assert cart_rules.check(cart_rules.apply(lines)) == []

    def test_zero_quantity_line_is_dropped(self):
        assert cart_rules.apply([CartLine(1, 0, product())]) == []


class TestAllowedToAdd:
    def test_empty_cart_takes_full_request(self):
        assert cart_rules.allowed_to_add(None, product(max_quantity=5), 3) == 3

    def test_request_capped_by_remaining_room(self):
        line = CartLine(1, 4, product(max_quantity=5))
        assert cart_rules.allowed_to_add(line, product(max_quantity=5), 3) == 1

    def test_full_cart_allows_nothing(self):
        line = CartLine(1, 5, product(max_quantity=5))
        assert cart_rules.allowed_to_add(line, product(max_quantity=5), 1) == 0

    def test_never_negative(self):
        """max_quantity can be lowered by an admin after items are already in carts."""
        line = CartLine(1, 9, product(max_quantity=5))
        assert cart_rules.allowed_to_add(line, product(max_quantity=5), 1) == 0

    def test_this_is_an_addition_not_an_assignment(self):
        """v1 bug #6: both add paths validated `in_cart + qty > max`, then assigned qty.

        Adding 2 to a cart holding 4 must yield 5 (clamped), never 2.
        """
        line = CartLine(1, 4, product(max_quantity=5))
        added = cart_rules.allowed_to_add(line, product(max_quantity=5), 2)
        assert line.qty + added == 5
