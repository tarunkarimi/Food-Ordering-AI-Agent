"""Personalization services built from authenticated order history."""

import json
from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from src.services.order_history import list_order_history


def get_personalization_summary(
    db: Session,
    *,
    user_id: int,
    restaurant_name: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Build a compact behavioral summary from the user's order history."""

    orders = list_order_history(
        db,
        user_id=user_id,
        limit=limit,
        offset=0,
    )

    if restaurant_name:
        restaurant_name_normalized = restaurant_name.strip().lower()
        orders = [
            order
            for order in orders
            if order.restaurant_name.strip().lower()
            == restaurant_name_normalized
        ]

    item_counts: Counter[str] = Counter()
    item_quantities: Counter[str] = Counter()
    last_order_items: list[dict[str, Any]] = []

    for order in orders:
        try:
            items = json.loads(order.items_json)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

        if not isinstance(items, list):
            continue

        if not last_order_items:
            last_order_items = items

        for item in items:
            if not isinstance(item, dict):
                continue

            title = str(
                item.get("title")
                or item.get("item_title")
                or item.get("name")
                or ""
            ).strip()

            if not title:
                continue

            quantity_raw = item.get("quantity", 1)

            try:
                quantity = int(quantity_raw)
            except (TypeError, ValueError):
                quantity = 1

            quantity = max(quantity, 1)

            item_counts[title] += 1
            item_quantities[title] += quantity

    usual_items = [
        {
            "title": title,
            "order_count": count,
            "total_quantity": item_quantities[title],
        }
        for title, count in item_counts.most_common(10)
    ]

    return {
        "orders_analyzed": len(orders),
        "usual_items": usual_items,
        "last_order_items": last_order_items,
    }
