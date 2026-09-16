from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from src.db.base import Base


class UserOrderingProfile(Base):
    __tablename__ = "user_ordering_profiles"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)

    total_orders = Column(Integer, nullable=False, default=0)
    total_items = Column(Integer, nullable=False, default=0)
    total_spend = Column(Numeric(12, 2), nullable=False, default=0)
    average_order_value = Column(Numeric(12, 2), nullable=False, default=0)

    last_order_id = Column(String(128), nullable=True)
    last_order_at = Column(DateTime(timezone=True), nullable=True)

    weekday_counts_json = Column(Text, nullable=False, default="{}")
    meal_period_counts_json = Column(Text, nullable=False, default="{}")

    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    user = relationship("User")


class UserOrderingItemStat(Base):
    __tablename__ = "user_ordering_item_stats"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    item_key = Column(String(255), nullable=False)
    item_title = Column(String(255), nullable=False)
    restaurant_name = Column(String(255), nullable=False)

    order_count = Column(Integer, nullable=False, default=0)
    total_quantity = Column(Integer, nullable=False, default=0)
    last_ordered_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "item_key",
            "restaurant_name",
            name="uq_user_ordering_item_stat",
        ),
    )

    user = relationship("User")


class UserOrderingRestaurantStat(Base):
    __tablename__ = "user_ordering_restaurant_stats"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    restaurant_name = Column(String(255), nullable=False)
    order_count = Column(Integer, nullable=False, default=0)
    total_spend = Column(Numeric(12, 2), nullable=False, default=0)
    last_ordered_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "restaurant_name",
            name="uq_user_ordering_restaurant_stat",
        ),
    )

    user = relationship("User")
