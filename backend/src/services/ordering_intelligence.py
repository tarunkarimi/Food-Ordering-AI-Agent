"""Advanced ordering intelligence service."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from src.services.order_history import list_order_history


def _load_items(order: Any) -> list[dict[str, Any]]:
    raw = getattr(order, "items_json", None)

    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]

    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]

    return []


def _item_key(item: dict[str, Any]) -> str:
    item_id = item.get("item_id", item.get("id"))
    if item_id is not None:
        return f"id:{item_id}"
    return f"title:{str(item.get('title', '')).strip().lower()}"


def _item_title(item: dict[str, Any]) -> str:
    return str(
        item.get("title")
        or item.get("name")
        or item.get("item_name")
        or ""
    ).strip()


def _quantity(item: dict[str, Any]) -> int:
    try:
        return max(1, int(item.get("quantity", 1)))
    except (TypeError, ValueError):
        return 1


def build_ordering_intelligence(
    db: Session,
    user_id: int | str,
    restaurant_name: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    orders = list_order_history(
        db,
        user_id=user_id,
        limit=max(1, min(limit, 100)),
        offset=0,
    )

    if restaurant_name:
        target = restaurant_name.strip().lower()
        orders = [
            order
            for order in orders
            if str(getattr(order, "restaurant_name", "")).strip().lower()
            == target
        ]

    item_orders: Counter[str] = Counter()
    item_quantities: Counter[str] = Counter()
    item_titles: dict[str, str] = {}
    restaurants: Counter[str] = Counter()
    combinations: Counter[tuple[str, ...]] = Counter()

    for order in orders:
        restaurant = str(getattr(order, "restaurant_name", "")).strip()
        if restaurant:
            restaurants[restaurant] += 1

        keys: list[str] = []

        for item in _load_items(order):
            title = _item_title(item)
            if not title:
                continue

            key = _item_key(item)
            item_titles[key] = title
            item_orders[key] += 1
            item_quantities[key] += _quantity(item)
            keys.append(key)

        unique_keys = tuple(sorted(set(keys)))
        if len(unique_keys) >= 2:
            combinations[unique_keys] += 1

    usual_items = sorted(
        (
            {
                "title": item_titles[key],
                "order_count": item_orders[key],
                "total_quantity": item_quantities[key],
            }
            for key in item_titles
        ),
        key=lambda item: (
            -item["order_count"],
            -item["total_quantity"],
            item["title"].lower(),
        ),
    )[:10]

    repeat_combinations = [
        {
            "items": [item_titles[key] for key in keys],
            "order_count": count,
        }
        for keys, count in combinations.most_common(5)
        if count >= 2
    ]

    latest_order = orders[0] if orders else None

    return {
        "orders_analyzed": len(orders),
        "usual_items": usual_items,
        "favorite_restaurants": [
            {"restaurant_name": name, "order_count": count}
            for name, count in restaurants.most_common(5)
        ],
        "repeat_combinations": repeat_combinations,
        "latest_order": (
            {
                "order_id": str(getattr(latest_order, "order_id", "")),
                "restaurant_name": getattr(
                    latest_order,
                    "restaurant_name",
                    None,
                ),
                "created_at": getattr(
                    latest_order,
                    "created_at",
                    None,
                ),
            }
            if latest_order
            else None
        ),
    }


def build_ai_ordering_context(
    db: Session,
    user_id: int | str,
    restaurant_name: str | None = None,
) -> dict[str, Any]:
    intelligence = build_ordering_intelligence(
        db,
        user_id=user_id,
        restaurant_name=restaurant_name,
        limit=30,
    )

    return {
        "orders_analyzed": intelligence["orders_analyzed"],
        "usual_items": intelligence["usual_items"][:5],
        "favorite_restaurants": intelligence["favorite_restaurants"][:3],
        "repeat_combinations": intelligence["repeat_combinations"][:3],
        "latest_order": intelligence["latest_order"],
    }


def build_smart_reorder_suggestions(
    db: Session,
    user_id: int | str,
    restaurant_name: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    intelligence = build_ordering_intelligence(
        db,
        user_id=user_id,
        restaurant_name=restaurant_name,
        limit=50,
    )

    suggestions = []

    for item in intelligence["usual_items"][: max(1, min(limit, 10))]:
        score = item["order_count"] * 10 + min(item["total_quantity"], 20)

        suggestions.append(
            {
                **item,
                "score": score,
                "reason": (
                    f"Ordered {item['order_count']} times"
                    if item["order_count"] > 1
                    else "Previously ordered"
                ),
            }
        )

    return suggestions
