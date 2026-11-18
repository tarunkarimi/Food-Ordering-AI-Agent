"""Durable menu-owned order storage and idempotency."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from fastapi import HTTPException
from functools import lru_cache


MENU_SCHEMA = "menu_backend"


class OrderBase(DeclarativeBase):
    pass


class MenuOrder(OrderBase):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "subdomain", "idempotency_key",
            name="uq_menu_order_idempotency_scope",
        ),
        CheckConstraint("status IN ('confirmed', 'cancelled')", name="ck_menu_order_status"),
        CheckConstraint("subtotal >= 0", name="ck_menu_order_subtotal_nonnegative"),
        {"schema": MENU_SCHEMA},
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    subdomain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    restaurant_name: Mapped[str] = mapped_column(String(255), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    subtotal: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    cancellation_reason: Mapped[str | None] = mapped_column(String(255))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    items: Mapped[list["MenuOrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin",
        order_by="MenuOrderItem.position",
    )


class MenuOrderItem(OrderBase):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_menu_order_item_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="ck_menu_order_item_price_nonnegative"),
        UniqueConstraint("order_id", "position", name="uq_menu_order_item_position"),
        {"schema": MENU_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(
        String(40), ForeignKey(f"{MENU_SCHEMA}.orders.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    item_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    variation_json: Mapped[str | None] = mapped_column(Text)
    order: Mapped[MenuOrder] = relationship(back_populates="items")


class OrderRepository(Protocol):
    def health(self) -> bool: ...
    def get_idempotent_order(
        self, *, user_id: str, subdomain: str, idempotency_key: str,
        fingerprint: str,
    ) -> dict[str, Any] | None: ...
    def create_order(self, order: dict[str, Any]) -> tuple[dict[str, Any], bool]: ...
    def get_order(self, order_id: str, *, user_id: str, subdomain: str) -> dict[str, Any] | None: ...
    def cancel_order(self, order_id: str, *, user_id: str, subdomain: str) -> dict[str, Any] | None: ...


def request_fingerprint(order: dict[str, Any]) -> str:
    normalized = json.dumps(order, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def serialize_order(order: MenuOrder) -> dict[str, Any]:
    return {
        "order_id": order.id,
        "restaurant_name": order.restaurant_name,
        "subdomain": order.subdomain,
        "items": [
            {
                "item_id": item.item_id,
                "title": item.title,
                "quantity": item.quantity,
                "base_price": float(item.unit_price),
                "variation": json.loads(item.variation_json) if item.variation_json else None,
            }
            for item in order.items
        ],
        "subtotal": float(order.subtotal),
        "status": order.status,
    }


class PostgresOrderRepository:
    """Uses only menu-backend-owned tables in the dedicated schema."""

    def __init__(self, database_url: str | None = None):
        url = database_url or os.getenv("MENU_DATABASE_URL", "")
        if not url:
            raise RuntimeError("Menu order storage is not configured.")
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        self.engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def health(self) -> bool:
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                # Readiness requires the independently migrated schema, not
                # just a reachable PostgreSQL server.
                revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
                if not isinstance(revision, str) or not revision.strip():
                    raise OrderStorageUnavailable
                connection.execute(text(
                    "SELECT id, user_id, subdomain, idempotency_key, "
                    "request_fingerprint, status FROM menu_backend.orders LIMIT 0"
                ))
                connection.execute(text(
                    "SELECT id, order_id, position, item_id, title, quantity, "
                    "unit_price, variation_json FROM menu_backend.order_items LIMIT 0"
                ))
            return True
        except OrderStorageUnavailable:
            raise
        except SQLAlchemyError as exc:
            raise OrderStorageUnavailable from exc

    def get_idempotent_order(
        self, *, user_id: str, subdomain: str, idempotency_key: str,
        fingerprint: str,
    ) -> dict[str, Any] | None:
        try:
            with self.sessions() as session:
                previous = session.scalar(select(MenuOrder).where(
                    MenuOrder.user_id == user_id,
                    MenuOrder.subdomain == subdomain,
                    MenuOrder.idempotency_key == idempotency_key,
                ))
                if previous is None:
                    return None
                if previous.request_fingerprint != fingerprint:
                    raise IdempotencyConflict
                return serialize_order(previous)
        except IdempotencyConflict:
            raise
        except SQLAlchemyError as exc:
            raise OrderStorageUnavailable from exc

    def create_order(self, order: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        fingerprint = order["request_fingerprint"]
        scope = (
            MenuOrder.user_id == order["user_id"],
            MenuOrder.subdomain == order["subdomain"],
            MenuOrder.idempotency_key == order["idempotency_key"],
        )
        try:
            with self.sessions() as session, session.begin():
                previous = session.scalar(select(MenuOrder).where(*scope))
                if previous:
                    if previous.request_fingerprint != fingerprint:
                        raise IdempotencyConflict
                    return serialize_order(previous), True

                record = MenuOrder(
                    id=f"ORD-{uuid4().hex.upper()}",
                    user_id=order["user_id"],
                    subdomain=order["subdomain"],
                    restaurant_name=order["restaurant_name"],
                    idempotency_key=order["idempotency_key"],
                    request_fingerprint=fingerprint,
                    status="confirmed",
                    subtotal=order["subtotal"],
                )
                record.items = [
                    MenuOrderItem(
                        position=position,
                        item_id=item["item_id"],
                        title=item["title"],
                        quantity=item["quantity"],
                        unit_price=item["base_price"],
                        variation_json=(
                            json.dumps(item["variation"], sort_keys=True)
                            if item.get("variation") is not None else None
                        ),
                    )
                    for position, item in enumerate(order["items"])
                ]
                session.add(record)
                session.flush()
                result = serialize_order(record)
            return result, False
        except IdempotencyConflict:
            raise
        except IntegrityError:
            # A concurrent request won the unique-key race. Read its committed result.
            try:
                with self.sessions() as session:
                    previous = session.scalar(select(MenuOrder).where(*scope))
                    if previous is None:
                        raise OrderStorageUnavailable
                    if previous.request_fingerprint != fingerprint:
                        raise IdempotencyConflict
                    return serialize_order(previous), True
            except (IdempotencyConflict, OrderStorageUnavailable):
                raise
            except SQLAlchemyError as exc:
                raise OrderStorageUnavailable from exc
        except SQLAlchemyError as exc:
            raise OrderStorageUnavailable from exc

    def get_order(self, order_id: str, *, user_id: str, subdomain: str) -> dict[str, Any] | None:
        try:
            with self.sessions() as session:
                order = session.scalar(select(MenuOrder).where(
                    MenuOrder.id == order_id,
                    MenuOrder.user_id == user_id,
                    MenuOrder.subdomain == subdomain,
                ))
                return serialize_order(order) if order else None
        except SQLAlchemyError as exc:
            raise OrderStorageUnavailable from exc

    def cancel_order(self, order_id: str, *, user_id: str, subdomain: str) -> dict[str, Any] | None:
        try:
            with self.sessions() as session, session.begin():
                order = session.scalar(select(MenuOrder).where(
                    MenuOrder.id == order_id,
                    MenuOrder.user_id == user_id,
                    MenuOrder.subdomain == subdomain,
                ).with_for_update())
                if order is None:
                    return None
                if order.status == "confirmed":
                    order.status = "cancelled"
                    order.cancelled_at = datetime.now(timezone.utc)
                    order.updated_at = datetime.now(timezone.utc)
                # Cancellation is idempotent so a lost response can be retried safely.
                return serialize_order(order)
        except SQLAlchemyError as exc:
            raise OrderStorageUnavailable from exc


class IdempotencyConflict(Exception):
    pass


class OrderStorageUnavailable(Exception):
    pass


@lru_cache(maxsize=1)
def get_order_repository() -> OrderRepository:
    try:
        return PostgresOrderRepository()
    except (RuntimeError, ArgumentError) as exc:
        raise HTTPException(status_code=503, detail="Order storage is not configured.") from exc
