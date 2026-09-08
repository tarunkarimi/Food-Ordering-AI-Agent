from __future__ import annotations

import inspect
from typing import Annotated, Any, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from src.agents.state import OrderState
from src.configs.config import config
from src.db.database import SessionLocal
from src.services.langgraph_cart import load_langgraph_cart
from src.services.reorder import (
    get_reorder_items,
    validate_reorder_items,
    add_reorder_items_to_cart,
)


def _failure(message: str, tool_call_id: str) -> Command:
    return Command(
        update={
            "messages": [
                ToolMessage(message, tool_call_id=tool_call_id)
            ]
        }
    )


def _call_service(function: Any, context: dict[str, Any]) -> Any:
    """
    Call an existing reorder service using its actual parameter names.

    This keeps the agent layer decoupled from the service parameter
    ordering while preserving the service as the business-logic source
    of truth.
    """
    signature = inspect.signature(function)

    kwargs: dict[str, Any] = {}

    for name, parameter in signature.parameters.items():
        if name in context:
            kwargs[name] = context[name]

    missing = [
        name
        for name, parameter in signature.parameters.items()
        if (
            parameter.default is inspect.Parameter.empty
            and parameter.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            )
            and name not in kwargs
        )
    ]

    if missing:
        raise TypeError(
            f"Unable to call {function.__name__}; "
            f"missing supported context parameters: {missing}"
        )

    return function(**kwargs)


def _extract_items(result: Any) -> list[dict]:
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]

    if isinstance(result, dict):
        for key in ("items", "validated_items", "reorder_items"):
            value = result.get(key)
            if isinstance(value, list):
                return [
                    item for item in value
                    if isinstance(item, dict)
                ]

    raise ValueError("Reorder service returned an invalid item list.")


def _item_summary(item: dict) -> str:
    title = str(
        item.get("title")
        or item.get("item_title")
        or item.get("name")
        or "Item"
    )

    quantity = item.get("quantity", 1)

    variation_name = (
        item.get("variation_name")
        or item.get("variation")
    )

    price = (
        item.get("unit_price")
        if item.get("unit_price") is not None
        else item.get("price")
    )

    text = f"{title} × {quantity}"

    if variation_name:
        text += f" ({variation_name})"

    if isinstance(price, (int, float)):
        text += f" — ₹{price:g} each"

    return text


@tool
def reorder_previous_order(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[OrderState, InjectedState],
    order_id: Optional[str] = None,
):
    """
    Reorder a previous authenticated order into the user's persistent cart.

    Use this for requests such as:
    - "reorder my last order"
    - "repeat my previous order"
    - "order what I had last time"
    - "get my usual order"
    - "repeat order <order id>"

    Historical prices are NEVER reused. The reorder service validates
    every item against the current menu and uses current authoritative
    pricing before modifying the persistent cart.

    This tool prepares the cart only. It does NOT place or pay for an
    order. The customer must still confirm before checkout.
    """

    user_id = state.get("user_id")

    if user_id is None:
        return _failure(
            "Reordering a previous order requires you to be signed in.",
            tool_call_id,
        )

    restaurant_name = state["restaurant_name"]
    subdomain = state["subdomain"]

    requested_order_id = order_id.strip() if order_id else None

    if requested_order_id == "":
        requested_order_id = None

    try:
        with SessionLocal() as db:
            context = {
                "db": db,
                "user_id": user_id,
                "order_id": requested_order_id,
                "restaurant_name": restaurant_name,
                "subdomain": subdomain,
            }

            historical_result = _call_service(
                get_reorder_items,
                context,
            )

            historical_items = _extract_items(historical_result)

            if not historical_items:
                return _failure(
                    "I couldn't find any items to reorder from that order.",
                    tool_call_id,
                )

            validation_context = {
                **context,
                "items": historical_items,
                "reorder_items": historical_items,
            }

            validated_result = _call_service(
                validate_reorder_items,
                validation_context,
            )

            validated_items = _extract_items(validated_result)

            if not validated_items:
                return _failure(
                    "None of the items from that order are currently "
                    "available to reorder.",
                    tool_call_id,
                )

            add_context = {
                **context,
                "items": validated_items,
                "validated_items": validated_items,
                "reorder_items": validated_items,
            }

            _call_service(
                add_reorder_items_to_cart,
                add_context,
            )

            cart = load_langgraph_cart(
                db,
                user_id=user_id,
                restaurant_name=restaurant_name,
                subdomain=subdomain,
            )

    except LookupError:
        return _failure(
            "I couldn't find that order in your order history.",
            tool_call_id,
        )
    except PermissionError:
        return _failure(
            "That order does not belong to your account.",
            tool_call_id,
        )
    except ValueError as exc:
        return _failure(
            str(exc) or "I couldn't reorder that order.",
            tool_call_id,
        )
    except Exception:
        return _failure(
            "I couldn't prepare that previous order right now. "
            "Please try again.",
            tool_call_id,
        )

    lines = [
        _item_summary(item)
        for item in validated_items
    ]

    message = (
        "I prepared your previous order in your current cart using "
        "today's menu and prices.\n\n"
        + "\n".join(f"- {line}" for line in lines)
        + "\n\nPlease review the cart and confirm when you're ready."
    )

    return Command(
        update={
            "cart": cart,
            "order_confirmation_pending": False,
            "finished": False,
            "messages": [
                ToolMessage(
                    message,
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )
