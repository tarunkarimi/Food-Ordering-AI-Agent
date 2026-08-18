from typing import Annotated, Optional

import requests
from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.types import Command
from langgraph.prebuilt import InjectedState

from src.agents.state import OrderState
from src.configs.config import config


def _failure(message: str, tool_call_id: str) -> ToolMessage:
    """Return a tool response without changing any order state."""
    return ToolMessage(message, tool_call_id=tool_call_id)


@tool
def get_order_status(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[OrderState, InjectedState],
    order_id: Optional[str] = None,
):
    """Look up an existing order's status using an order ID, or the most recent order."""
    requested_order_id = order_id or state.get("orderId")
    if not requested_order_id:
        return _failure(
            "There is no active or recent order to check. Please provide an order ID.",
            tool_call_id,
        )

    order_url = f"{config.MENU_BACKEND_URL.rstrip('/')}/orders/{requested_order_id}"
    try:
        response = requests.get(order_url, timeout=10)
        if response.status_code == 404:
            return _failure(f"Order {requested_order_id} was not found.", tool_call_id)
        response.raise_for_status()
        order = response.json()
        if not isinstance(order, dict) or not isinstance(order.get("order_id"), str):
            raise ValueError("Order API response is missing order_id")

        restaurant = order.get("restaurant_name")
        status = order.get("status")
        subtotal = order.get("subtotal")
        items = order.get("items")
        if not isinstance(restaurant, str) or not isinstance(status, str):
            raise ValueError("Order API response is malformed")
        if not isinstance(subtotal, (int, float)) or not isinstance(items, list):
            raise ValueError("Order API response is malformed")

        item_lines = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Order API response is malformed")
            title = item.get("title")
            quantity = item.get("quantity")
            base_price = item.get("base_price")
            if not isinstance(title, str) or not isinstance(quantity, int):
                raise ValueError("Order API response is malformed")
            if not isinstance(base_price, (int, float)):
                raise ValueError("Order API response is malformed")
            item_lines.append(f"- {title} × {quantity} — ₹{base_price * quantity:g}")
    except requests.Timeout:
        return _failure("Unable to check order status: the ordering service timed out.", tool_call_id)
    except requests.ConnectionError:
        return _failure("Unable to check order status: the ordering service is unavailable.", tool_call_id)
    except requests.RequestException as exc:
        return _failure(
            f"Unable to check order status: the ordering service returned an error ({exc}).",
            tool_call_id,
        )
    except (ValueError, TypeError, AttributeError):
        return _failure("Unable to check order status: the ordering service returned an invalid response.", tool_call_id)

    return ToolMessage(
        f"Order {order['order_id']} is {status}.\n\n"
        f"Restaurant: {restaurant}\n\n"
        f"Items:\n" + "\n".join(item_lines) + f"\n\nTotal: ₹{subtotal:g}\nStatus: {status}",
        tool_call_id=tool_call_id,
    )


@tool
def cancel_order(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[OrderState, InjectedState],
    order_id: Optional[str] = None,
):
    """Cancel an existing order using an order ID, or the most recent order."""
    requested_order_id = order_id or state.get("orderId")
    if not requested_order_id:
        return Command(update={
            "messages": [_failure(
                "There is no active or recent order to cancel. Please provide an order ID.",
                tool_call_id,
            )]
        })

    order_url = f"{config.MENU_BACKEND_URL.rstrip('/')}/orders/{requested_order_id}"
    try:
        response = requests.delete(order_url, timeout=10)
        if response.status_code == 404:
            return Command(update={
                "messages": [_failure(f"Order {requested_order_id} was not found.", tool_call_id)]
            })
        response.raise_for_status()
        order = response.json()
        if not isinstance(order, dict) or not isinstance(order.get("order_id"), str):
            raise ValueError("Order API response is missing order_id")
        if order.get("status") != "cancelled":
            raise ValueError("Order API response did not confirm cancellation")
    except requests.Timeout:
        message = "Unable to cancel order: the ordering service timed out."
    except requests.ConnectionError:
        message = "Unable to cancel order: the ordering service is unavailable."
    except requests.RequestException as exc:
        message = f"Unable to cancel order: the ordering service returned an error ({exc})."
    except (ValueError, TypeError, AttributeError):
        message = "Unable to cancel order: the ordering service returned an invalid response."
    else:
        return Command(update={
            "order_status": "cancelled",
            "messages": [ToolMessage(
                f"Order {order['order_id']} has been cancelled successfully.",
                tool_call_id=tool_call_id,
            )],
        })

    return Command(update={"messages": [_failure(message, tool_call_id)]})
