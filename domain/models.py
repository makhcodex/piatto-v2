"""Value objects crossing the domain boundary.

These fix the shape of a cart in one place. v1 had three different cart
representations because the shape was never written down.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

ProblemKind = Literal["gone", "out_of_stock", "over_max"]


@dataclass(frozen=True)
class ProductView:
    """A product as the rules need to see it. Built by services from a DB row."""

    id: int
    name: str
    unit_price: Decimal
    max_quantity: int
    in_stock: bool
    is_deleted: bool


@dataclass(frozen=True)
class CartLine:
    """One cart row. `product` is None when the product no longer exists."""

    product_id: int
    qty: int
    product: ProductView | None


@dataclass(frozen=True)
class CartProblem:
    """A reason a line cannot stand as requested.

    Carries facts, not text. Handlers render these into user-facing messages —
    the domain never produces strings for display.
    """

    product_id: int
    kind: ProblemKind
    product_name: str | None = None
    allowed_qty: int | None = None
