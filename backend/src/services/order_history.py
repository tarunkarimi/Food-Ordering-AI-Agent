"""Persistent authenticated order-history services."""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import OrderHistory


def create_order_history(
    db: Session,
    *,
    user_id: int,
    order_id: str,
    restaurant_name: str,
    subdomain: str,
    status: str,
    subtotal: float,
    total_items: int,
    items: list[dict[str, Any]],
) -> OrderHistory:
    existing = db.scalar(
        select(OrderHistory).where(
            OrderHistory.order_id == order_id,
        )
    )

    if existing is not None:
        if existing.user_id != user_id:
            raise ValueError("Order history belongs to another user.")
        return existing

    order = OrderHistory(
        user_id=user_id,
        order_id=order_id,
        restaurant_name=restaurant_name,
        subdomain=subdomain,
        status=status,
        subtotal=subtotal,
        total_items=total_items,
        items_json=json.dumps(items),
    )

    db.add(order)
    db.flush()
    return order


def list_order_history(
    db: Session,
    *,
    user_id: int,
    limit: int = 50,
    offset: int = 0,
    subdomain: str | None = None,
    restaurant_name: str | None = None,
) -> list[OrderHistory]:
    query = select(OrderHistory).where(OrderHistory.user_id == user_id)
    if subdomain and subdomain.strip():
        query = query.where(OrderHistory.subdomain == subdomain.strip())
    if restaurant_name and restaurant_name.strip():
        query = query.where(OrderHistory.restaurant_name == restaurant_name.strip())
    return list(
        db.scalars(
            query.order_by(
                OrderHistory.created_at.desc(),
                OrderHistory.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
    )


def resolve_unique_order_subdomain(
    db: Session,
    *,
    user_id: int | str,
) -> str | None:
    """Resolve a tenant only when this user's history has exactly one.

    Restaurant display names are deliberately not used as tenant identity.
    Null, blank, or multiple subdomains fail closed.
    """
    values = db.scalars(
        select(OrderHistory.subdomain)
        .where(
            OrderHistory.user_id == user_id,
            OrderHistory.subdomain.is_not(None),
            OrderHistory.subdomain != "",
        )
        .distinct()
        .limit(2)
    ).all()
    if (
        len(values) != 1
        or not isinstance(values[0], str)
        or not values[0].strip()
        or values[0] != values[0].strip()
    ):
        return None
    return values[0]


def get_order_history(
    db: Session,
    *,
    user_id: int,
    order_id: str,
) -> OrderHistory | None:
    return db.scalar(
        select(OrderHistory).where(
            OrderHistory.user_id == user_id,
            OrderHistory.order_id == order_id,
        )
    )


def update_order_history_status(
    db: Session,
    *,
    user_id: int,
    order_id: str,
    status: str,
) -> OrderHistory | None:
    order = get_order_history(
        db,
        user_id=user_id,
        order_id=order_id,
    )

    if order is None:
        return None

    order.status = status
    db.commit()
    db.refresh(order)
    return order
