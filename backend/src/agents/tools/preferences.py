"""AI tools for authenticated user preferences."""

from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from src.agents.state import OrderState
from src.db.database import SessionLocal
from src.services.user_preferences import (
    get_user_preferences,
    update_user_preferences,
)


def _serialize_preferences(preferences) -> dict[str, Any] | None:
    if preferences is None:
        return None

    return {
        "cuisine_preference": preferences.cuisine_preference,
        "spice_level": preferences.spice_level,
        "dietary_preference": preferences.dietary_preference,
        "meal_preference": preferences.meal_preference,
        "notes": preferences.notes,
    }


@tool
def get_my_preferences(
    state: Annotated[OrderState, InjectedState],
) -> dict[str, Any]:
    """Read the authenticated user's explicitly saved food preferences.

    Use this when the user asks about saved preferences or when explicit
    preferences are relevant to a recommendation.

    These are explicit user-provided preferences, not inferred history.
    This tool does not modify the cart or place an order.
    """

    user_id = state.get("user_id")

    if user_id is None:
        return {
            "message": "Please sign in so I can access your saved preferences.",
        }

    try:
        with SessionLocal() as db:
            preferences = get_user_preferences(
                db,
                user_id=user_id,
            )

            if preferences is None:
                return {
                    "message": "You don't have any saved food preferences yet.",
                    "preferences": None,
                }

            return {
                "preferences": _serialize_preferences(preferences),
            }

    except Exception:
        return {
            "message": "I couldn't access your saved preferences right now.",
        }


@tool
def update_my_preferences(
    state: Annotated[OrderState, InjectedState],
    cuisine_preference: str | None = None,
    spice_level: str | None = None,
    dietary_preference: str | None = None,
    meal_preference: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Save explicit food preferences provided by the authenticated user.

    Use this only when the user explicitly asks to remember, save, update,
    or change a preference.

    Do not infer a permanent preference merely from a single order or
    recommendation request.

    This tool changes only persistent preferences. It does not modify the
    cart and does not place an order.
    """

    user_id = state.get("user_id")

    if user_id is None:
        return {
            "message": "Please sign in so I can save your preferences.",
        }

    try:
        with SessionLocal() as db:
            preferences = update_user_preferences(
                db,
                user_id=user_id,
                cuisine_preference=cuisine_preference,
                spice_level=spice_level,
                dietary_preference=dietary_preference,
                meal_preference=meal_preference,
                notes=notes,
            )

            return {
                "message": "Your food preferences have been saved.",
                "preferences": _serialize_preferences(preferences),
            }

    except ValueError as exc:
        return {
            "message": str(exc),
        }
    except Exception:
        return {
            "message": "I couldn't save your food preferences right now.",
        }
