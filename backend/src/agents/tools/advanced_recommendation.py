"""AI tool for advanced multi-constraint recommendations."""

import json
from datetime import datetime, timezone
from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from src.agents.state import OrderState
from src.agents.tools.cart import _fetch_menu_items
from src.db.database import SessionLocal
from src.services.order_history import list_order_history
from src.services.ai_memory import list_user_memories
from src.services.recommendation_ranking import (
    build_budget_combinations,
    extract_budget,
    has_unknown_dietary_evidence,
    has_unknown_memory_restriction,
    rank_recommendations,
)
from src.services.user_preferences import get_user_preferences

_SAFETY_NOTICE = (
    "Some menu items were excluded because ingredient information is "
    "incomplete. Their safety against your stated restrictions could not be "
    "verified; please confirm ingredients with the restaurant."
)


def _extract_budget(messages: list[Any]) -> float | None:
    """Compatibility wrapper for the shared explicit-budget parser."""
    return extract_budget(messages)


def _build_history_counts(
    orders: list[Any],
) -> dict[str, int]:
    """Build recent order frequency counts from persisted order snapshots."""
    return {
        title: signal["order_count"]
        for title, signal in _build_history_signals(orders).items()
    }


def _build_history_signals(
    orders: list[Any],
) -> dict[str, dict[str, Any]]:
    """Summarize unique orders, quantities, and newest purchase timestamps."""
    history: dict[str, dict[str, Any]] = {}

    for order in orders:
        if str(getattr(order, "status", "")).strip().lower() in {
            "cancelled", "canceled", "failed", "rejected"
        }:
            continue
        try:
            items = json.loads(order.items_json)
        except (
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            continue

        if not isinstance(items, list):
            continue

        order_items: dict[str, int] = {}
        for item in items:
            if not isinstance(item, dict):
                continue

            title = str(
                item.get("title")
                or item.get("item_title")
                or item.get("name")
                or ""
            ).strip().lower()

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
            signal = history.setdefault(
                title,
                {"order_count": 0, "total_quantity": 0, "last_ordered_at": None},
            )
            signal["order_count"] += 1
            signal["total_quantity"] += quantity
            if isinstance(timestamp, datetime) and (
                signal["last_ordered_at"] is None
                or timestamp > signal["last_ordered_at"]
            ):
                signal["last_ordered_at"] = timestamp

    return history


@tool
def advanced_recommend_food(
    state: Annotated[OrderState, InjectedState],
) -> dict[str, Any]:
    """Solve a multi-constraint personalized food recommendation.

    Combines saved preferences, tenant-scoped recent order behavior, explicit
    budget constraints, and current menu availability/pricing. Persistent
    lifetime aggregates are omitted because their schema is not tenant-keyed.

    Current menu data is authoritative.

    Never modifies the cart or places an order.
    """

    user_id = state.get("user_id")

    if user_id is None:
        return {
            "message": (
                "Please sign in so I can personalize the recommendation."
            )
        }

    menu_items, error = _fetch_menu_items(state)

    if error:
        return {"message": error}

    max_price = _extract_budget(
        state.get("messages", [])
    )

    try:
        with SessionLocal() as db:
            preferences = get_user_preferences(
                db,
                user_id=user_id,
            )
            ai_memories = list_user_memories(
                db,
                user_id=user_id,
            )

            orders = list_order_history(
                db,
                user_id=user_id,
                limit=20,
                offset=0,
                subdomain=(
                    str(state.get("subdomain")).strip()
                    if state.get("subdomain") else None
                ),
                restaurant_name=(
                    str(state.get("restaurant_name")).strip()
                    if state.get("restaurant_name") else None
                ),
            )
            eligible_orders = [
                order
                for order in orders
                if str(getattr(order, "subdomain", "")).strip().casefold()
                == str(state.get("subdomain") or "").strip().casefold()
                and bool(str(state.get("subdomain") or "").strip())
                and (
                    not state.get("restaurant_name")
                    or str(getattr(order, "restaurant_name", "")).strip().casefold()
                    == str(state.get("restaurant_name")).strip().casefold()
                )
                if str(getattr(order, "status", "")).strip().lower()
                not in {"cancelled", "canceled", "failed", "rejected"}
            ]

            history_signals = _build_history_signals(eligible_orders)
            history_counts = {
                title: signal["order_count"]
                for title, signal in history_signals.items()
            }

            # Persistent aggregates are keyed by display name, not tenant.
            # Do not use them for product ranking because duplicate restaurant
            # names could mix different subdomains. Recent history above is
            # scoped by the stable subdomain instead.
            persistent_context = None

            recommendations = rank_recommendations(
                menu_items,
                cuisine_preference=(
                    preferences.cuisine_preference
                    if preferences
                    else None
                ),
                spice_level=(
                    preferences.spice_level
                    if preferences
                    else None
                ),
                dietary_preference=(
                    preferences.dietary_preference
                    if preferences
                    else None
                ),
                meal_preference=(
                    preferences.meal_preference
                    if preferences
                    else None
                ),
                history_counts=history_counts,
                history_signals=history_signals,
                persistent_context=persistent_context,
                current_restaurant=state.get(
                    "restaurant_name"
                ),
                max_price=max_price,
                limit=5,
                ai_memories=ai_memories,
            )

    except Exception:
        return {
            "message": (
                "I couldn't build an advanced recommendation right now."
            )
        }

    if not recommendations:
        if max_price is not None:
            result = {
                "message": (
                    "I couldn't find a suitable current-menu item "
                    f"within the requested budget of ₹{max_price:g}."
                ),
                "recommendations": [],
            }
            if any(
                has_unknown_memory_restriction(item, ai_memories)
                or has_unknown_dietary_evidence(
                    item,
                    preferences.dietary_preference if preferences else None,
                )
                for item in menu_items
            ):
                result["safety_notice"] = _SAFETY_NOTICE
                result["message"] += " " + _SAFETY_NOTICE
            return result

        result = {
            "message": (
                "I couldn't find a suitable current-menu recommendation "
                "using your available preferences."
            ),
            "recommendations": [],
        }
        if any(
            has_unknown_memory_restriction(item, ai_memories)
            or has_unknown_dietary_evidence(
                item,
                preferences.dietary_preference if preferences else None,
            )
            for item in menu_items
        ):
            result["safety_notice"] = _SAFETY_NOTICE
            result["message"] += " " + _SAFETY_NOTICE
        return result

    result = {
        "recommendations": recommendations,
        "budget_combinations": build_budget_combinations(
            recommendations,
            max_price,
        ),
        "budget_applied": max_price,
        "preferences_used": bool(preferences or ai_memories),
        "orders_analyzed": len(eligible_orders),
        "persistent_intelligence_used": False,
    }
    if any(
        has_unknown_memory_restriction(item, ai_memories)
        or has_unknown_dietary_evidence(
            item,
            preferences.dietary_preference if preferences else None,
        )
        for item in menu_items
    ):
        result["recommendations_limited"] = True
        result["safety_notice"] = _SAFETY_NOTICE
    else:
        result["recommendations_limited"] = False
    return result
