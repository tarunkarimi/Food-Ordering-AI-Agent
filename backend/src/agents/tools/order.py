from math import isfinite
import hashlib
import logging
from typing import Annotated, Optional
from urllib.parse import quote

import requests
from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.types import Command
from langgraph.prebuilt import InjectedState

from src.agents.state import OrderState
from src.configs.config import config
from src.db.database import SessionLocal
from src.services.order_history import (
    get_order_history,
    update_order_history_status,
)
from src.services.order_operations import (
    OperationConflict,
    begin_operation,
    mark_operation_complete,
    mark_operation_retryable,
    mark_upstream_confirmed,
    operation_response,
)
from src.observability import log_event


logger = logging.getLogger(__name__)
from src.services.menu_backend import menu_service_headers


def _failure(message: str, tool_call_id: str) -> ToolMessage:
    """Return a tool response without changing any order state."""
    return ToolMessage(message, tool_call_id=tool_call_id)


def _owned_order_context(state: OrderState, order_id: str) -> dict | None:
    """Allow only a graph's active order or history owned by its user."""
    user_id = state.get("user_id")
    if user_id is None:
        return None

    if state.get("orderId") == order_id:
        return {
            "order_id": order_id,
            "restaurant_name": state.get("restaurant_name"),
            "subdomain": state.get("subdomain"),
            "user_id": user_id,
            "is_active_graph_order": True,
            "history_persisted": bool(state.get("order_history_persisted")),
        }

    with SessionLocal() as db:
        order = get_order_history(
            db,
            user_id=user_id,
            order_id=order_id,
        )
        if order is None:
            return None
        return {
            "order_id": order.order_id,
            "restaurant_name": order.restaurant_name,
            "subdomain": order.subdomain,
            "user_id": user_id,
            "is_active_graph_order": False,
            "history_persisted": True,
        }


def _matches_order_identity(order: dict, context: dict) -> bool:
    return (
        order.get("order_id") == context["order_id"]
        and order.get("restaurant_name") == context["restaurant_name"]
        and order.get("subdomain") == context["subdomain"]
    )


class _OrderNotFound(Exception):
    """The menu service authoritatively reports that the owned order is absent."""


def _cancel_with_outbox(order_context: dict) -> dict:
    """Persist cancellation intent and reconcile the authoritative result on retries."""
    order_id = order_context["order_id"]
    user_id = int(order_context["user_id"])
    subdomain = order_context["subdomain"]
    payload = {
        "order_id": order_id,
        "subdomain": subdomain,
        "restaurant_name": order_context["restaurant_name"],
    }
    idempotency_key = f"cancel:{user_id}:{order_id}"
    order_url = f"{config.MENU_BACKEND_URL.rstrip('/')}/orders/{quote(order_id, safe='')}"

    with SessionLocal() as db:
        operation = begin_operation(
            db,
            user_id=user_id,
            operation_type="cancellation",
            idempotency_key=idempotency_key,
            order_id=order_id,
            subdomain=subdomain,
            payload=payload,
        )
        log_event(
            logger,
            "agent_cancellation.intent_created" if operation.attempts == 1 else "agent_cancellation.reconciliation_attempt",
            operation_id=operation.id,
            attempt=operation.attempts,
        )

        order = operation_response(operation)
        if operation.status == "completed":
            if (
                not isinstance(order, dict)
                or order.get("order_id") != order_id
                or order.get("status") != "cancelled"
            ):
                raise RuntimeError("Cancellation result is pending reconciliation.")
            return {
                **order,
                "restaurant_name": order_context["restaurant_name"],
                "subdomain": subdomain,
            }
        if operation.status not in {"completed", "upstream_confirmed"}:
            try:
                # Commit has persisted the cancellation intent; close any
                # transaction opened by refreshing that row before I/O.
                db.commit()
                log_event(logger, "agent_cancellation.upstream_attempt", operation_id=operation.id)
                response = requests.delete(
                    order_url,
                    params={"subdomain": subdomain, "user_id": str(user_id)},
                    headers=menu_service_headers(),
                    timeout=10,
                )
                if response.status_code == 404:
                    mark_operation_retryable(db, operation, error_code="order_not_found")
                    raise _OrderNotFound
                response.raise_for_status()
                order = response.json()
                if (
                    not isinstance(order, dict)
                    or not _matches_order_identity(order, order_context)
                    or order.get("status") != "cancelled"
                ):
                    mark_operation_retryable(db, operation, error_code="invalid_cancel_response")
                    log_event(logger, "agent_cancellation.invalid_upstream_response", level=logging.WARNING, operation_id=operation.id)
                    raise ValueError("The cancellation response could not be verified.")
                mark_upstream_confirmed(
                    db,
                    operation,
                    order_id=order_id,
                    response=order,
                )
                log_event(logger, "agent_cancellation.upstream_confirmed", operation_id=operation.id)
            except requests.Timeout:
                mark_operation_retryable(db, operation, error_code="cancel_timeout")
                log_event(logger, "agent_cancellation.retryable_failure", level=logging.WARNING, operation_id=operation.id, error_type="timeout")
                raise
            except requests.ConnectionError:
                mark_operation_retryable(db, operation, error_code="cancel_unavailable")
                log_event(logger, "agent_cancellation.retryable_failure", level=logging.WARNING, operation_id=operation.id, error_type="connection")
                raise
            except requests.RequestException:
                mark_operation_retryable(db, operation, error_code="cancel_upstream_error")
                log_event(logger, "agent_cancellation.retryable_failure", level=logging.WARNING, operation_id=operation.id, error_type="request")
                raise

        if not isinstance(order, dict) or not _matches_order_identity(order, order_context):
            raise RuntimeError("Cancellation result is pending reconciliation.")

        if order_context.get("history_persisted"):
            update_order_history_status(
                db,
                user_id=user_id,
                order_id=order_id,
                status="cancelled",
            )

        result = {"success": True, "order_id": order_id, "status": "cancelled"}
        mark_operation_complete(db, operation, response=result)
        log_event(logger, "agent_cancellation.reconciliation_succeeded", operation_id=operation.id)
        return order


@tool
def get_order_status(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[OrderState, InjectedState],
    order_id: Optional[str] = None,
):
    """Look up an existing order's status using an order ID, or the most recent order."""
    requested_order_id = order_id or state.get("orderId")
    if not isinstance(requested_order_id, str) or not requested_order_id.strip():
        return _failure(
            "There is no active or recent order to check. Please provide an order ID.",
            tool_call_id,
        )

    requested_order_id = requested_order_id.strip()
    try:
        order_context = _owned_order_context(state, requested_order_id)
    except Exception:
        order_context = None
    if order_context is None:
        return _failure(
            "I can only check orders associated with your account.",
            tool_call_id,
        )
    if not isinstance(order_context.get("subdomain"), str) or not order_context["subdomain"].strip():
        return _failure(
            "I can only check orders with a verified restaurant identity.",
            tool_call_id,
        )

    order_url = f"{config.MENU_BACKEND_URL.rstrip('/')}/orders/{quote(requested_order_id, safe='')}"
    try:
        response = requests.get(
            order_url,
            params={
                "subdomain": order_context["subdomain"],
                "user_id": str(order_context["user_id"]),
            },
            headers=menu_service_headers(),
            timeout=10,
        )
        if response.status_code == 404:
            return _failure(f"Order {requested_order_id} was not found.", tool_call_id)
        response.raise_for_status()
        order = response.json()
        if not isinstance(order, dict) or not _matches_order_identity(order, order_context):
            raise ValueError("Order API response is missing order_id")

        restaurant = order.get("restaurant_name")
        status = order.get("status")
        subtotal = order.get("subtotal")
        items = order.get("items")
        if not isinstance(restaurant, str) or not isinstance(status, str):
            raise ValueError("Order API response is malformed")
        if (
            not isinstance(subtotal, (int, float))
            or isinstance(subtotal, bool)
            or not isfinite(subtotal)
            or subtotal < 0
            or not isinstance(items, list)
        ):
            raise ValueError("Order API response is malformed")

        item_lines = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Order API response is malformed")
            title = item.get("title")
            quantity = item.get("quantity")
            base_price = item.get("base_price")
            if (
                not isinstance(title, str)
                or not isinstance(quantity, int)
                or isinstance(quantity, bool)
                or quantity <= 0
            ):
                raise ValueError("Order API response is malformed")
            if (
                not isinstance(base_price, (int, float))
                or isinstance(base_price, bool)
                or not isfinite(base_price)
                or base_price < 0
            ):
                raise ValueError("Order API response is malformed")
            item_lines.append(f"- {title} × {quantity} — ₹{base_price * quantity:g}")
    except requests.Timeout:
        return _failure("Unable to check order status: the ordering service timed out.", tool_call_id)
    except requests.ConnectionError:
        return _failure("Unable to check order status: the ordering service is unavailable.", tool_call_id)
    except requests.RequestException:
        return _failure(
            "Unable to check order status: the ordering service returned an error.",
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
    if not isinstance(requested_order_id, str) or not requested_order_id.strip():
        return Command(update={
            "messages": [_failure(
                "There is no active or recent order to cancel. Please provide an order ID.",
                tool_call_id,
            )]
        })

    requested_order_id = requested_order_id.strip()
    try:
        order_context = _owned_order_context(state, requested_order_id)
    except Exception:
        order_context = None
    if order_context is None:
        return Command(update={
            "messages": [_failure(
                "I can only cancel orders associated with your account.",
                tool_call_id,
            )]
        })
    if not isinstance(order_context.get("subdomain"), str) or not order_context["subdomain"].strip():
        return Command(update={
            "messages": [_failure(
                "I can only cancel orders with a verified restaurant identity.",
                tool_call_id,
            )]
        })

    try:
        order = _cancel_with_outbox(order_context)
    except _OrderNotFound:
        return Command(update={
            "messages": [_failure(f"Order {requested_order_id} was not found.", tool_call_id)]
        })
    except OperationConflict:
        message = "This cancellation conflicts with an existing order operation. Please check the order status."
    except requests.Timeout:
        message = "Unable to cancel order: the ordering service timed out."
    except requests.ConnectionError:
        message = "Unable to cancel order: the ordering service is unavailable."
    except requests.RequestException:
        message = "Unable to cancel order: the ordering service returned an error."
    except (ValueError, TypeError, AttributeError):
        message = "Unable to cancel order: the ordering service returned an invalid response."
    except Exception:
        message = "The order was cancelled or is being reconciled, but its status could not be saved. Retry cancellation or check order status."

    else:
        return Command(update={
            "order_status": "cancelled",
            "messages": [ToolMessage(
                f"Order {order['order_id']} has been cancelled successfully.",
                tool_call_id=tool_call_id,
            )],
        })

    return Command(update={"messages": [_failure(message, tool_call_id)]})
