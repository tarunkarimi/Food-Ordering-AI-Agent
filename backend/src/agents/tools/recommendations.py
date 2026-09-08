"""AI tool for context-aware current-menu recommendations."""

from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from src.agents.state import OrderState
from src.agents.tools.cart import _fetch_menu_items
from src.db.database import SessionLocal
from src.services.recommendations import get_personalized_recommendations


@tool
def get_personalized_recommendations(
    state: Annotated[OrderState, InjectedState],
) -> dict[str, Any]:
    """Recommend currently available menu items using the authenticated
    user's saved preferences and previous ordering behavior.

    Use this for requests such as:
    - recommend something for me
    - what should I get
    - suggest something based on my preferences
    - suggest something based on my previous orders

    The current menu is authoritative for availability and price.

    This tool never modifies the cart and never places an order.
    """

    user_id = state.get("user_id")

    if user_id is None:
        return {
            "message": (
                "Please sign in so I can personalize recommendations "
                "using your saved preferences and order history."
            )
        }

    menu_items, error = _fetch_menu_items(state)

    if error:
        return {
            "message": error,
        }

    try:
        with SessionLocal() as db:
            result = get_personalized_recommendations(
                db,
                user_id=user_id,
                menu_items=menu_items,
                limit=5,
            )
    except Exception:
        return {
            "message": (
                "I couldn't build a personalized recommendation right now."
            )
        }

    recommendations = result.get("recommendations", [])

    if not recommendations:
        return {
            "message": (
                "I couldn't find a suitable current-menu recommendation "
                "from your saved preferences and available menu."
            ),
            "recommendations": [],
        }

    return result
