import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Enum, ForeignKey, Integer,
    Numeric, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class OrderStatus(enum.StrEnum):
    """Real enum, not a bare string — v1 stored this as String(20)."""

    PENDING = "pending"
    PAID = "paid"
    PREPARING = "preparing"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    CANCELLED_UNPAID = "cancelled_unpaid"


ACTIVE_STATUSES = frozenset({
    OrderStatus.PENDING,
    OrderStatus.PAID,
    OrderStatus.PREPARING,
    OrderStatus.DELIVERING,
})

# Each status -> the next one an admin may set.
NEXT_STATUS = {
    OrderStatus.PENDING: OrderStatus.PAID,
    OrderStatus.PAID: OrderStatus.PREPARING,
    OrderStatus.PREPARING: OrderStatus.DELIVERING,
    OrderStatus.DELIVERING: OrderStatus.DELIVERED,
}


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)

    products: Mapped[list["Product"]] = relationship(back_populates="category")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    orders: Mapped[list["Order"]] = relationship(back_populates="user")
    cart_items: Mapped[list["CartItem"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Real FK. v1 joined products to categories by matching strings
    # (Product.category == Category.slug) via primaryjoin.
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("categories.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    in_stock: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    max_quantity: Mapped[int] = mapped_column(Integer, server_default="10", nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)

    category: Mapped["Category"] = relationship(back_populates="products")
    order_items: Mapped[list["OrderItem"]] = relationship(back_populates="product")


class CartItem(Base):
    """Persistent cart. Quantity only — no price column, by design.

    A stored price is the sole reason v1 needed price reconciliation on every
    cart read. Price is always read live from products; it is snapshotted once,
    at order creation, into order_items.price.
    """

    __tablename__ = "cart_items"
    __table_args__ = (UniqueConstraint("user_id", "product_id", name="uq_cart_user_product"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="cart_items")
    product: Mapped["Product"] = relationship()


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status", native_enum=True),
        default=OrderStatus.PENDING,
        nullable=False,
        index=True,
    )
    total_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    # Written by the sweep job. v1 declared this column but never read or wrote it.
    warning_sent: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)

    # No reminder_job_id / cancel_job_id: the sweep keeps its state here, in orders.

    user: Mapped["User"] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    # The one and only price snapshot in the system. Immutable once written.
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    order: Mapped["Order"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship(back_populates="order_items")
