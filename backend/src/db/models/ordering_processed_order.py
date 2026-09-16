from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from src.db.base import Base


class UserOrderingProcessedOrder(Base):
    __tablename__ = "user_ordering_processed_orders"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id = Column(String(128), nullable=False)
    processed_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "order_id",
            name="uq_user_ordering_processed_order",
        ),
    )

    user = relationship("User")
