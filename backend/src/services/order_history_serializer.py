"""Serialization helpers for persistent order history."""

import json
from typing import Any

from src.db.models import OrderHistory


def serialize_order_history(order: OrderHistory) -> dict[str, Any]:
    """Convert a persistent order-history record into an API-safe payload."""

    try:
        items = json.loads(order.items_json)
    except (TypeError, ValueError):
        items = []

    return {
        "id": order.id,
        "order_id": order.order_id,
        "restaurant_name": order.restaurant_name,
        "subdomain": order.subdomain,
        "status": order.status,
        "subtotal": float(order.subtotal),
        "total_items": order.total_items,
        "items": items,
        "created_at": (
            order.created_at.isoformat()
            if order.created_at is not None
            else None
        ),
        "updated_at": (
            order.updated_at.isoformat()
            if order.updated_at is not None
            else None
        ),
    }
