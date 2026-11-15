"""Context-aware recommendation services."""

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from src.services.ai_memory import list_user_memories
from src.services.order_history import list_order_history
from src.services.recommendation_ranking import (
    build_budget_combinations,
    has_unknown_dietary_evidence,
    has_unknown_memory_restriction,
    rank_recommendations,
)
from src.services.user_preferences import get_user_preferences


def _normalize(value: object) -> str:
    return str(value).strip().lower() if value is not None else ""


def get_personalized_recommendations(
    db: Session,
    *,
    user_id: int,
    menu_items: list[dict[str, Any]],
    limit: int = 5,
    max_price: float | None = None,
    restaurant_name: str | None = None,
    subdomain: str | None = None,
) -> dict[str, Any]:
    """Rank current menu items using explicit preferences and order history.

    Current menu data is authoritative. This function never mutates the
    cart and never uses historical prices.
    """

    preferences = get_user_preferences(db, user_id=user_id)
    ai_memories = list_user_memories(db, user_id=user_id)

    cuisine_preference = (
        preferences.cuisine_preference
        if preferences is not None
        else None
    )
    spice_level = (
        preferences.spice_level
        if preferences is not None
        else None
    )
    dietary_preference = (
        preferences.dietary_preference
        if preferences is not None
        else None
    )
    meal_preference = (
        preferences.meal_preference
        if preferences is not None
        else None
    )

    history_filters = {}
    if subdomain and subdomain.strip():
        history_filters["subdomain"] = subdomain.strip()
        if restaurant_name and restaurant_name.strip():
            history_filters["restaurant_name"] = restaurant_name.strip()
    orders = list_order_history(
        db,
        user_id=user_id,
        limit=20,
        offset=0,
        **history_filters,
    )
    # Order-history signals are tenant scoped. Without a stable subdomain we
    # retain global preferences, but do not guess which restaurant history fits.
    eligible_orders = []
    if subdomain and subdomain.strip():
        tenant = subdomain.strip().casefold()
        restaurant = _normalize(restaurant_name)
        eligible_orders = [
            order for order in orders
            if str(getattr(order, "subdomain", "")).strip().casefold() == tenant
            and (not restaurant or _normalize(getattr(order, "restaurant_name", "")) == restaurant)
            and str(getattr(order, "status", "")).strip().lower()
            not in {"cancelled", "canceled", "failed", "rejected"}
        ]

    history_counts: dict[str, int] = {}
    history_signals: dict[str, dict[str, Any]] = {}

    for order in eligible_orders:
        try:
            items = json.loads(order.items_json)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

        if not isinstance(items, list):
            continue

        order_items: dict[str, int] = {}
        for item in items:
            if not isinstance(item, dict):
                continue

            title = _normalize(
                item.get("title")
                or item.get("item_title")
                or item.get("name")
            )

            if title:
                try:
                    quantity = max(1, int(item.get("quantity", 1)))
                except (TypeError, ValueError):
                    quantity = 1
                order_items[title] = order_items.get(title, 0) + quantity

        timestamp = getattr(order, "created_at", None)
        if isinstance(timestamp, datetime):
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            else:
                timestamp = timestamp.astimezone(timezone.utc)
        for title, quantity in order_items.items():
            detail = history_signals.setdefault(
                title,
                {"order_count": 0, "total_quantity": 0, "last_ordered_at": None},
            )
            detail["order_count"] += 1
            detail["total_quantity"] += quantity
            if isinstance(timestamp, datetime) and (
                detail["last_ordered_at"] is None
                or timestamp > detail["last_ordered_at"]
            ):
                detail["last_ordered_at"] = timestamp
            history_counts[title] = detail["order_count"]

    recommendations = rank_recommendations(
        menu_items,
        cuisine_preference=cuisine_preference,
        spice_level=spice_level,
        dietary_preference=dietary_preference,
        meal_preference=meal_preference,
        history_counts=history_counts,
        history_signals=history_signals,
        ai_memories=ai_memories,
        max_price=max_price,
        limit=limit,
    )

    limited_by_safety = any(
        has_unknown_memory_restriction(item, ai_memories)
        or has_unknown_dietary_evidence(item, dietary_preference)
        for item in menu_items
        if isinstance(item, dict)
    )
    result = {
        "recommendations": recommendations[: max(1, limit)],
        "budget_combinations": build_budget_combinations(
            recommendations,
            max_price,
        ),
        "budget_applied": max_price,
        "preferences_used": bool(preferences or ai_memories),
        "orders_analyzed": len(eligible_orders),
    }
    if limited_by_safety:
        result["recommendations_limited"] = True
        result["safety_notice"] = (
            "Some menu items were excluded because ingredient information is "
            "incomplete. Their safety against your stated restrictions could "
            "not be verified; please confirm ingredients with the restaurant."
        )
    else:
        result["recommendations_limited"] = False
    return result
