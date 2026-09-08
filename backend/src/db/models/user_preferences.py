"""Persistent user preference database model."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


class UserPreferences(Base):
    """Explicit food preferences associated with one application user."""

    __tablename__ = "user_preferences"

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

    cuisine_preference: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    spice_level: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )

    dietary_preference: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    meal_preference: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
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
