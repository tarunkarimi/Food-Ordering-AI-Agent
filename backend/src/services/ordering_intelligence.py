"""Advanced ordering intelligence service."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from math import isfinite
from typing import Any

from sqlalchemy.orm import Session

from src.services.order_history import (
    list_order_history,
    resolve_unique_order_subdomain,
)


def _load_items(order: Any) -> list[dict[str, Any]]:
    raw = getattr(order, "items_json", None)

    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    if not isinstance(raw, list):
        return []

    return [item for item in raw if isinstance(item, dict)]


def _item_key(item: dict[str, Any]) -> str:
    item_id = item.get("item_id", item.get("id"))
    if item_id is not None:
        return f"id:{item_id}"
    return f"title:{str(item.get('title') or item.get('name') or '').strip().lower()}"


def _item_title(item: dict[str, Any]) -> str:
    return str(
        item.get("title")
        or item.get("name")
        or item.get("item_title")
        or item.get("item_name")
        or ""
    ).strip()


def _quantity(item: dict[str, Any]) -> int:
    try:
        return max(1, int(item.get("quantity", 1)))
    except (TypeError, ValueError):
        return 1


def _order_timestamp(order: Any) -> datetime | None:
    value = getattr(order, "created_at", None)
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def is_menu_item_available(item: dict[str, Any]) -> bool:
    """Validate current-menu availability evidence.

    The menu backend exposes current catalog membership as its orderability
    contract; an omitted flag is therefore accepted. Explicit malformed flags
    or statuses fail closed because they cannot confirm availability.
    """
    for field in ("available", "is_available", "is_active"):
        if field in item and (
            not isinstance(item[field], bool) or item[field] is False
        ):
            return False
    if "status" in item:
        if not isinstance(item.get("status"), str):
            return False
        status = item["status"].strip().lower()
        if status not in {"available", "active", "in stock", "in_stock"}:
            return False
    return True


def filter_reorder_suggestions_to_menu(
    suggestions: list[dict[str, Any]],
    menu_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep suggestions only when the current menu confirms item and price."""
    by_id = {
        str(item.get("id")): item
        for item in menu_items
        if isinstance(item, dict) and item.get("id") is not None
    }
    by_title = {
        str(item.get("title") or "").strip().casefold(): item
        for item in menu_items
        if isinstance(item, dict) and str(item.get("title") or "").strip()
    }
    filtered = []
    for suggestion in suggestions:
        item_id = suggestion.get("item_id")
        current = (
            by_id.get(str(item_id))
            if item_id is not None
            else by_title.get(str(suggestion.get("title") or "").strip().casefold())
        )
        if current is None or not is_menu_item_available(current):
            continue
        current_title = str(current.get("title") or "").strip()
        if current_title.casefold() != str(suggestion.get("title") or "").strip().casefold():
            continue
        if isinstance(current.get("base_price", current.get("price")), bool):
            continue
        try:
            price = float(current.get("base_price", current.get("price")))
        except (TypeError, ValueError):
            continue
        if not isfinite(price) or price < 0:
            continue
        filtered.append(
            {
                **suggestion,
                "title": current_title,
                "current_price": price,
            }
        )
    return filtered


def build_ordering_intelligence(
    db: Session,
    user_id: int | str,
    restaurant_name: str | None = None,
    limit: int = 50,
    subdomain: str | None = None,
) -> dict[str, Any]:
    tenant = subdomain.strip() if isinstance(subdomain, str) else ""
    if not tenant:
        tenant = resolve_unique_order_subdomain(db, user_id=user_id) or ""
    if not tenant:
        return _empty_ordering_intelligence()

    history_filters = {"subdomain": tenant}
    if restaurant_name and restaurant_name.strip():
        history_filters["restaurant_name"] = restaurant_name.strip()
    orders = list_order_history(
        db,
        user_id=user_id,
        limit=max(1, min(limit, 100)),
        offset=0,
        **history_filters,
    )
    orders = [
        order
        for order in orders
        if getattr(order, "subdomain", None) == tenant
        and (
            not restaurant_name
            or str(getattr(order, "restaurant_name", "")).strip().casefold()
            == restaurant_name.strip().casefold()
        )
        and str(getattr(order, "status", "")).strip().lower()
        not in {"cancelled", "canceled", "failed", "rejected"}
    ]

    item_orders: Counter[str] = Counter()
    item_quantities: Counter[str] = Counter()
    item_titles: dict[str, str] = {}
    item_ids: dict[str, str | None] = {}
    item_restaurants: dict[str, str] = {}
    item_last_ordered: dict[str, datetime | None] = {}
    item_last_quantity: dict[str, int] = {}
    restaurants: Counter[tuple[str, str]] = Counter()
    restaurant_names: dict[tuple[str, str], str] = {}
    combinations: Counter[tuple[str, ...]] = Counter()

    for order in orders:
        restaurant = str(getattr(order, "restaurant_name", "")).strip()
        if restaurant:
            restaurant_key = (tenant.casefold(), restaurant.casefold())
            restaurants[restaurant_key] += 1
            restaurant_names[restaurant_key] = restaurant

        keys: list[str] = []
        order_quantities: Counter[str] = Counter()
        order_timestamp = _order_timestamp(order)

        for item in _load_items(order):
            title = _item_title(item)
            if not title:
                continue

            key = f"{tenant.casefold()}::{restaurant.casefold()}::{_item_key(item)}"
            item_titles[key] = title
            item_ids[key] = str(item.get("item_id") or item.get("id") or "") or None
            item_restaurants[key] = restaurant
            order_quantities[key] += _quantity(item)
            keys.append(key)

        for key, quantity in order_quantities.items():
            item_orders[key] += 1
            item_quantities[key] += quantity
            if (
                order_timestamp is not None
                and (
                    item_last_ordered.get(key) is None
                    or order_timestamp > item_last_ordered[key]
                )
            ):
                item_last_ordered[key] = order_timestamp
                item_last_quantity[key] = quantity

        unique_keys = tuple(sorted(set(keys)))
        if len(unique_keys) >= 2:
            combinations[unique_keys] += 1

    usual_items = sorted(
        (
            {
                "title": item_titles[key],
                "item_id": item_ids.get(key),
                "restaurant_name": item_restaurants.get(key),
                "order_count": item_orders[key],
                "total_quantity": item_quantities[key],
                "last_ordered_at": item_last_ordered.get(key),
                "last_order_quantity": item_last_quantity.get(key, 1),
            }
            for key in item_titles
        ),
        key=lambda item: (
            -item["order_count"],
            -item["total_quantity"],
            item["title"].lower(),
        ),
    )

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
        "usual_items": usual_items[:10],
        "favorite_restaurants": [
            {
                "restaurant_name": restaurant_names[key],
                "order_count": count,
            }
            for key, count in restaurants.most_common(5)
        ],
        "repeat_combinations": repeat_combinations,
        "latest_order": (
            {
                "order_id": str(getattr(latest_order, "order_id", "")),
                "restaurant_name": getattr(
                    latest_order, "restaurant_name", None
                ),
                "created_at": getattr(latest_order, "created_at", None),
            }
            if latest_order
            else None
        ),
    }


def _empty_ordering_intelligence() -> dict[str, Any]:
    """Return the established empty response when tenant identity is unclear."""
    return {
        "orders_analyzed": 0,
        "usual_items": [],
        "favorite_restaurants": [],
        "repeat_combinations": [],
        "latest_order": None,
    }


def build_ai_ordering_context(
    db: Session,
    user_id: int | str,
    restaurant_name: str | None = None,
    subdomain: str | None = None,
) -> dict[str, Any]:
    intelligence = build_ordering_intelligence(
        db,
        user_id=user_id,
        restaurant_name=restaurant_name,
        limit=30,
        subdomain=subdomain,
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
    now: datetime | None = None,
    subdomain: str | None = None,
) -> list[dict[str, Any]]:
    intelligence = build_ordering_intelligence(
        db,
        user_id=user_id,
        restaurant_name=restaurant_name,
        limit=50,
        subdomain=subdomain,
    )

    suggestions = []
    reference_time = now or datetime.now(timezone.utc)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)

    for item in intelligence["usual_items"]:
        last_ordered = item.get("last_ordered_at")
        age_days = None
        recency_score = 0
        if isinstance(last_ordered, datetime):
            if last_ordered.tzinfo is None:
                last_ordered = last_ordered.replace(tzinfo=timezone.utc)
            age_days = max(
                0,
                (reference_time - last_ordered.astimezone(timezone.utc)).days,
            )
            recency_score = (
                10 if age_days <= 7 else
                6 if age_days <= 30 else
                3 if age_days <= 90 else 0
            )
        repeated = item["order_count"] >= 2
        score = (
            min(item["order_count"], 5) * 10 if repeated else 1
        ) + min(item["total_quantity"], 5) + recency_score

        suggestions.append(
            {
                **item,
                "score": score,
                "frequency_type": "repeat_favorite" if repeated else "one_time",
                "reason": (
                    (
                        f"Ordered {item['order_count']} times"
                        if repeated
                        else "Previously ordered once"
                    )
                    + (
                        f"; last ordered {age_days} days ago"
                        if age_days is not None
                        else ""
                    )
                ),
            }
        )

    ranked = sorted(
        suggestions,
        key=lambda item: (
            -item["score"],
            item["title"].lower(),
        ),
    )
    return ranked[: max(1, min(limit, 10))]
