"""Persistent shopping-cart database models."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base


class Cart(Base):
    """One persistent active cart owned by one user."""

    __tablename__ = "carts"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    restaurant_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    subdomain: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    items: Mapped[list["CartItem"]] = relationship(
        back_populates="cart",
        cascade="all, delete-orphan",
        order_by="CartItem.id",
    )


class CartItem(Base):
    """Persistent cart line representing one item/variation combination."""

    __tablename__ = "cart_items"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    cart_id: Mapped[int] = mapped_column(
        ForeignKey("carts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    item_key: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
    )

    item_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    quantity: Mapped[int] = mapped_column(
        nullable=False,
    )

    unit_price: Mapped[float] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    variation_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    variation_name: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    variation_price: Mapped[float | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )

    cart: Mapped[Cart] = relationship(
        back_populates="items",
    )

    __table_args__ = (
        UniqueConstraint(
            "cart_id",
            "item_key",
            name="uq_cart_items_cart_item_key",
        ),
    )
