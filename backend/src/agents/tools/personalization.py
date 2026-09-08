"""AI tools for authenticated user personalization."""

from typing import Any

from langchain_core.tools import tool

from src.db.database import SessionLocal
from src.services.personalization import get_personalization_summary


def _call_service(
    user_id: int,
    restaurant_name: str | None,
) -> dict[str, Any]:
    with SessionLocal() as db:
        return get_personalization_summary(
            db,
            user_id=user_id,
            restaurant_name=restaurant_name,
        )


@tool
def get_my_food_preferences(
    user_id: int,
    restaurant_name: str | None = None,
) -> dict[str, Any]:
    """Inspect the authenticated user's previous orders and summarize
    their food preferences.

    Use this for questions about:
    - usual orders
    - favorite or commonly ordered food
    - previous purchases
    - recommendations based on ordering history

    This tool provides historical preference signals only.

    Historical prices and historical availability must never be treated
    as current. For a recommendation intended for an actual purchase,
    combine this tool's result with the current menu data from get_menu.

    This tool does not modify the cart or place an order.
    """

    if not user_id:
        return {
            "message": "Please sign in so I can use your previous orders.",
        }

    try:
        summary = _call_service(
            user_id=user_id,
            restaurant_name=restaurant_name,
        )
    except Exception:
        return {
            "message": "I couldn't access your previous order preferences right now.",
        }

    if not summary.get("orders_analyzed"):
        return {
            "message": (
                "I don't have enough previous orders yet to identify "
                "your preferences."
            ),
            "orders_analyzed": 0,
            "usual_items": [],
            "last_order_items": [],
        }

    return summary
