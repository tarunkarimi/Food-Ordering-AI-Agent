"""AI tool for advanced multi-constraint recommendations."""

import json
import re
from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from src.agents.state import OrderState
from src.agents.tools.cart import _fetch_menu_items
from src.db.database import SessionLocal
from src.services.order_history import list_order_history
from src.services.recommendation_ranking import rank_recommendations
from src.services.user_preferences import get_user_preferences


def _extract_budget(messages: list[Any]) -> float | None:
    """Extract the latest explicit per-item budget from conversation text."""

    budget_pattern = re.compile(
        r"(?:under|below|within|max(?:imum)?(?:\s+of)?)\s*"
        r"(?:rs\.?|inr|\u20b9|\?)?\s*"
        r"(\d+(?:\.\d+)?)",
        flags=re.IGNORECASE,
    )

    for message in reversed(messages):
        content = getattr(message, "content", "")

        if not isinstance(content, str):
            continue

        match = budget_pattern.search(content)

        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None

    return None


@tool
def advanced_recommend_food(
    state: Annotated[OrderState, InjectedState],
) -> dict[str, Any]:
    """Solve a multi-constraint personalized food recommendation.

    Combines authenticated saved preferences, previous order behavior,
    explicit budget constraints, and current menu availability/pricing.

    Never modifies the cart or places an order.
    """

    user_id = state.get("user_id")

    if user_id is None:
        return {
            "message": "Please sign in so I can personalize the recommendation."
        }

    menu_items, error = _fetch_menu_items(state)

    if error:
        return {"message": error}

    max_price = _extract_budget(state.get("messages", []))

    try:
        with SessionLocal() as db:
            preferences = get_user_preferences(
                db,
                user_id=user_id,
            )

            orders = list_order_history(
                db,
                user_id=user_id,
                limit=20,
                offset=0,
            )

            history_counts: dict[str, int] = {}

            for order in orders:
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
                        history_counts[title] = (
                            history_counts.get(title, 0) + 1
                        )

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
                max_price=max_price,
                limit=5,
            )

    except Exception:
        return {
            "message": "I couldn't build an advanced recommendation right now."
        }

    if not recommendations:
        if max_price is not None:
            return {
                "message": (
                    "I couldn't find a suitable current-menu item "
                    f"within the requested budget of ₹{max_price:g}."
                ),
                "recommendations": [],
            }

        return {
            "message": (
                "I couldn't find a suitable current-menu recommendation "
                "using your available preferences."
            ),
            "recommendations": [],
        }

    return {
        "recommendations": recommendations,
        "budget_applied": max_price,
        "preferences_used": bool(preferences),
        "orders_analyzed": len(orders),
    }
