"""Persistent conversational AI memory database model."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


class UserAIMemory(Base):
    """Explicit food-related preference learned from authenticated chat."""

    __tablename__ = "user_ai_memories"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    memory_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    memory_key: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    memory_value: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    polarity: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )

    confidence: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=0.8,
    )

    mention_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "memory_type",
            "memory_key",
            "memory_value",
            "polarity",
            name="uq_user_ai_memory",
        ),
    )
