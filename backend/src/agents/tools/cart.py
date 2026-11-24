import requests
import hashlib
import logging
from src.db.database import SessionLocal
from src.services.order_history import create_order_history
from src.services.order_operations import (
    OperationConflict,
    begin_operation,
    fingerprint,
    mark_operation_complete,
    mark_operation_retryable,
    mark_upstream_confirmed,
    operation_response,
)
from src.configs.config import config
from langchain_core.tools import tool, InjectedToolCallId
from langgraph.types import Command
from langchain_core.messages import HumanMessage, ToolMessage
from typing import Annotated
from src.agents.state import (
    CartItemUnit,
    Cart,
    CartItem,
    OrderState,
    ItemVariation,
)
from langgraph.prebuilt import InjectedState
from src.services.http_resilience import request_read_with_retry
from src.services.menu_backend import menu_service_headers
from src.services.ordering_intelligence import is_menu_item_available
from src.observability import log_event


logger = logging.getLogger(__name__)


def _menu_url(subdomain: str) -> str:
    return f"{config.MENU_BACKEND_URL.rstrip('/')}/?subdomain={subdomain}"


def _fetch_menu_response(subdomain: str) -> tuple[dict | None, str | None]:
    """Fetch a menu only when its envelope confirms the requested tenant."""
    if not isinstance(subdomain, str) or not subdomain.strip():
        return None, "A valid restaurant identity is required to load the menu."
    requested = subdomain.strip()
    try:
        response = request_read_with_retry(
            lambda: requests.get(
                _menu_url(requested),
                timeout=config.DOWNSTREAM_REQUEST_TIMEOUT_SECONDS,
            )
        )
        response.raise_for_status()
        menu = response.json()

        if not isinstance(menu, dict) or not isinstance(menu.get("items"), list):
            raise ValueError("Menu response is malformed")

        returned = menu.get("subdomain")
        if not isinstance(returned, str) or not returned.strip():
            return None, "The menu service returned an invalid restaurant identity."
        if returned != requested:
            return None, "The menu service returned a different restaurant menu."

        items = menu["items"]

        if not all(isinstance(item, dict) for item in items):
            raise ValueError("Menu response is malformed")

        return menu, None

    except requests.Timeout:
        return None, "The menu service timed out. Please try again."

    except requests.ConnectionError:
        return None, "The menu service is unavailable. Please try again."

    except requests.RequestException:
        return None, "The menu service returned an error. Please try again."

    except (ValueError, TypeError, AttributeError):
        return None, "The menu service returned an invalid response. Please try again."


def _fetch_menu_items(state: OrderState) -> tuple[list[dict], str | None]:
    """Fetch the current menu items for the restaurant in agent state."""
    tenant = state.get("subdomain") if isinstance(state, dict) else None
    menu, error = _fetch_menu_response(tenant)
    if error:
        return [], error
    return menu["items"], None


def _fetch_menu_items_for_tenant(
    subdomain: str,
) -> tuple[list[dict], str | None]:
    """Fetch menu items only when the response confirms the requested tenant."""
    menu, error = _fetch_menu_response(subdomain)
    if error:
        return [], error
    return menu["items"], None


def _failure(message: str, tool_call_id: str) -> Command:
    return Command(
        update={
            "messages": [
                ToolMessage(message, tool_call_id=tool_call_id)
            ]
        }
    )


def _place_order_with_outbox(
    *,
    payload: dict,
    idempotency_key: str,
    order_url: str,
) -> tuple[dict, int]:
    """Persist an authenticated tool checkout intent and reconcile its result."""
    user_id = int(payload["user_id"])
    total_items = sum(item["quantity"] for item in payload["items"])
    with SessionLocal() as db:
        operation = begin_operation(
            db,
            user_id=user_id,
            operation_type="chat_checkout",
            idempotency_key=idempotency_key,
            order_id=None,
            subdomain=payload["subdomain"],
            payload=payload,
        )
        log_event(
            logger,
            "agent_checkout.intent_created" if operation.attempts == 1 else "agent_checkout.reconciliation_attempt",
            operation_id=operation.id,
            attempt=operation.attempts,
        )
        if operation.status in {"completed", "upstream_confirmed"}:
            result = operation_response(operation)
        else:
            try:
                # The intent is durable; release the read transaction before
                # making a potentially slow network call.
                db.commit()
                log_event(logger, "agent_checkout.upstream_attempt", operation_id=operation.id)
                response = requests.post(
                    order_url,
                    json=payload,
                    headers={
                        **menu_service_headers(),
                        "Idempotency-Key": idempotency_key,
                    },
                    timeout=10,
                )
                response.raise_for_status()
                result = response.json()
                if not isinstance(result, dict):
                    raise ValueError("Order API response is malformed")
                if (
                    not _valid_order_id(result.get("order_id"))
                    or result.get("status") != "confirmed"
                    or not _valid_price(result.get("subtotal"))
                ):
                    raise ValueError("Order API response is invalid")
                mark_upstream_confirmed(
                    db,
                    operation,
                    order_id=result["order_id"],
                    response=result,
                )
                log_event(logger, "agent_checkout.upstream_accepted", operation_id=operation.id)
            except requests.Timeout:
                mark_operation_retryable(db, operation, error_code="upstream_timeout")
                log_event(logger, "agent_checkout.retryable_failure", level=logging.WARNING, operation_id=operation.id, error_type="timeout")
                raise
            except requests.ConnectionError:
                mark_operation_retryable(db, operation, error_code="upstream_unavailable")
                log_event(logger, "agent_checkout.retryable_failure", level=logging.WARNING, operation_id=operation.id, error_type="connection")
                raise
            except requests.RequestException:
                mark_operation_retryable(db, operation, error_code="upstream_error")
                log_event(logger, "agent_checkout.retryable_failure", level=logging.WARNING, operation_id=operation.id, error_type="request")
                raise
            except (ValueError, TypeError, AttributeError):
                mark_operation_retryable(db, operation, error_code="invalid_upstream_response")
                log_event(logger, "agent_checkout.retryable_failure", level=logging.WARNING, operation_id=operation.id, error_type="invalid_response")
                raise

        if not isinstance(result, dict):
            raise RuntimeError("Order result is pending reconciliation")
        order_id = result["order_id"]
        try:
            create_order_history(
                db,
                user_id=user_id,
                order_id=order_id,
                restaurant_name=payload["restaurant_name"],
                subdomain=payload["subdomain"],
                status=result["status"],
                subtotal=float(result["subtotal"]),
                total_items=total_items,
                items=payload["items"],
            )
            operation.order_id = order_id
            mark_operation_complete(db, operation, response=result, commit=False)
            db.commit()
        except Exception:
            db.rollback()
            log_event(logger, "agent_checkout.reconciliation_failure", level=logging.ERROR, operation_id=operation.id)
            raise
        log_event(logger, "agent_checkout.reconciliation_succeeded", operation_id=operation.id)
        return result, total_items


def _valid_quantity(quantity: object) -> bool:
    return (
        isinstance(quantity, int)
        and not isinstance(quantity, bool)
        and quantity > 0
    )


def _valid_price(price: object) -> bool:
    return (
        isinstance(price, (int, float))
        and not isinstance(price, bool)
        and price == price
        and price not in (float("inf"), float("-inf"))
        and price >= 0
    )


def _valid_order_id(order_id: object) -> bool:
    return isinstance(order_id, str) and bool(order_id.strip())


@tool
def get_menu(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[OrderState, InjectedState],
):
    """Provide the latest up-to-date menu."""

    items, error = _fetch_menu_items(state)

    if error:
        return ToolMessage(error, tool_call_id=tool_call_id)

    return items


@tool
def add_cart(
    item_id: str,
    title: str,
    new_item: CartItemUnit,
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[OrderState, InjectedState],
):
    """
    Adds an item to the cart.

    The menu backend is authoritative for:
    - item existence
    - item title
    - base price
    - valid variations

    If the menu item has no variations, any hallucinated
    variation supplied by the LLM is ignored.
    """

    # ---------------------------------------------------------
    # 1. Validate quantity
    # ---------------------------------------------------------
    if not _valid_quantity(new_item.quantity):
        return _failure(
            "Quantity must be greater than zero.",
            tool_call_id
        )

    # ---------------------------------------------------------
    # 2. Fetch authoritative menu
    # ---------------------------------------------------------
    items, error = _fetch_menu_items(state)

    if error:
        return _failure(
            f"Cannot add item: {error}",
            tool_call_id
        )

    # ---------------------------------------------------------
    # 3. Find requested menu item
    # ---------------------------------------------------------
    menu_item = next(
        (
            item
            for item in items
            if item.get("id") == item_id
        ),
        None
    )

    if menu_item is None or menu_item.get("title") != title:
        return _failure(
            "That item is not available on the current menu.",
            tool_call_id
        )

    if not is_menu_item_available(menu_item):
        return _failure(
            "That menu item is not currently available.",
            tool_call_id,
        )

    # ---------------------------------------------------------
    # 4. Validate authoritative base price
    # ---------------------------------------------------------
    authoritative_price = menu_item.get("base_price")

    if not _valid_price(authoritative_price):
        return _failure(
            "That menu item has invalid pricing and cannot be added.",
            tool_call_id
        )

    # ---------------------------------------------------------
    # 5. Handle variations
    #
    # IMPORTANT:
    # If the menu has no variations, completely ignore
    # whatever variation the LLM sends.
    # ---------------------------------------------------------
    variations = menu_item.get("variations", [])

    if not isinstance(variations, list):
        return _failure(
            "That item has invalid variation data on the current menu.",
            tool_call_id
        )

    variation_id = "no_variant"
    valid_variation = None

    # ---------------------------------------------------------
    # CASE A: Item has NO variations
    # ---------------------------------------------------------
    if len(variations) == 0:

        # Ignore hallucinated values such as:
        # "default"
        # "Standard"
        # "Base"
        # "item-001"
        #
        # The menu says there are no variations.
        variation_id = "no_variant"
        valid_variation = None

    # ---------------------------------------------------------
    # CASE B: Item HAS variations
    # ---------------------------------------------------------
    else:

        if new_item.variation is None:
            return _failure(
                "Please specify a valid variation for this item.",
                tool_call_id
            )

        requested_variation_id = new_item.variation.id.strip()

        if not requested_variation_id:
            return _failure(
                "A valid variation ID is required.",
                tool_call_id
            )

        # Find the variation in the authoritative menu.
        menu_variation = next(
            (
                variation
                for variation in variations
                if (
                    isinstance(variation, dict)
                    and variation.get("id") == requested_variation_id
                )
            ),
            None
        )

        if menu_variation is None:
            return _failure(
                "That item variation is not available on the current menu.",
                tool_call_id
            )

        variation_id = requested_variation_id

        raw_variation_price = menu_variation.get(
            "price",
            authoritative_price
        )

        try:
            variation_price = float(raw_variation_price)
        except (TypeError, ValueError):
            return _failure(
                "That item variation has invalid pricing on the current menu.",
                tool_call_id
            )

        if not _valid_price(variation_price):
            return _failure(
                "That item variation has invalid pricing on the current menu.",
                tool_call_id
            )

        valid_variation = ItemVariation(
            id=menu_variation["id"],
            name=str(menu_variation.get("name", "")),
            price=str(raw_variation_price)
        )

        # IMPORTANT:
        # The selected variation price is the actual cart unit price.
        authoritative_price = variation_price

    # ---------------------------------------------------------
    # 6. Create deterministic cart key
    # ---------------------------------------------------------
    item_key = f"{item_id}|{variation_id}"

    # ---------------------------------------------------------
    # 7. Create authoritative cart unit
    # ---------------------------------------------------------
    updated_unit = CartItemUnit(
        key=item_key,
        quantity=new_item.quantity,
        base_price=authoritative_price,
        variation=valid_variation
    )

    # ---------------------------------------------------------
    # 8. Get current cart
    # ---------------------------------------------------------
    current_cart = state.get("cart")

    if current_cart is None:

        new_cart_item = CartItem(
            item_id=item_id,
            title=title,
            units=[updated_unit]
        )

        updated_cart = Cart(
            items=[new_cart_item]
        )

    else:

        item_found = False
        updated_items = []

        # -----------------------------------------------------
        # 9. Update existing cart
        # -----------------------------------------------------
        for existing_item in current_cart.items:

            if existing_item.item_id == item_id:

                unit_found = False
                updated_units = []

                for existing_unit in existing_item.units:

                    if existing_unit.key == item_key:

                        # Same item + same variation:
                        # increase quantity.
                        updated_units.append(
                            CartItemUnit(
                                key=existing_unit.key,
                                quantity=(
                                    existing_unit.quantity
                                    + new_item.quantity
                                ),
                                # Use the authoritative current price and
                                # variation from the menu.
                                base_price=updated_unit.base_price,
                                variation=updated_unit.variation
                            )
                        )

                        unit_found = True

                    else:

                        updated_units.append(existing_unit)

                # New variation for an existing item.
                if not unit_found:
                    updated_units.append(updated_unit)

                updated_items.append(
                    CartItem(
                        item_id=existing_item.item_id,
                        title=existing_item.title,
                        units=updated_units
                    )
                )

                item_found = True

            else:

                updated_items.append(existing_item)

        # -----------------------------------------------------
        # 10. Completely new item
        # -----------------------------------------------------
        if not item_found:

            new_cart_item = CartItem(
                item_id=item_id,
                title=title,
                units=[updated_unit]
            )

            updated_items.append(new_cart_item)

        updated_cart = Cart(
            items=updated_items
        )

    # ---------------------------------------------------------
    # 11. Return updated state
    # ---------------------------------------------------------
    return Command(
        update={
            "cart": updated_cart,
            "order_confirmation_pending": False,

            # Starting a new cart begins a new active-order lifecycle.
            # Keep the previous orderId/order_status available for status
            # lookups, but allow this new cart to be placed as a new order.
            "finished": False,

            "messages": [
                ToolMessage(
                    f"Added {title} to cart",
                    tool_call_id=tool_call_id
                )
            ]
        }
    )


@tool
def remove_from_cart(
    item_id: str,
    title: str,
    new_item: CartItemUnit,
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[OrderState, InjectedState]
):
    """
    Removes an item from the cart.

    For variation-based items, the exact variation ID is used
    to determine which cart unit should be removed.
    """

    # ---------------------------------------------------------
    # 1. Validate quantity
    # ---------------------------------------------------------
    if not _valid_quantity(new_item.quantity):
        return _failure(
            "Quantity must be greater than zero.",
            tool_call_id
        )

    # ---------------------------------------------------------
    # 2. Handle variation ID safely
    # ---------------------------------------------------------
    variation_id = "no_variant"

    if new_item.variation is not None:

        if not new_item.variation.id:
            return _failure(
                "A valid variation ID is required.",
                tool_call_id
            )

        variation_id = new_item.variation.id.strip()

        if not variation_id:
            return _failure(
                "A valid variation ID is required.",
                tool_call_id
            )

    item_key = f"{item_id}|{variation_id}"

    # ---------------------------------------------------------
    # 3. Get current cart
    # ---------------------------------------------------------
    current_cart = state.get("cart")

    if current_cart is None or not current_cart.items:
        return _failure(
            f"Item {title} not found in cart.",
            tool_call_id
        )

    # ---------------------------------------------------------
    # 4. Remove requested quantity
    # ---------------------------------------------------------
    updated_items = []
    item_found = False

    for existing_item in current_cart.items:

        if existing_item.item_id != item_id:

            updated_items.append(existing_item)
            continue

        unit_found = False
        updated_units = []

        for existing_unit in existing_item.units:

            if existing_unit.key != item_key:

                updated_units.append(existing_unit)
                continue

            unit_found = True

            if existing_unit.quantity > new_item.quantity:

                updated_units.append(
                    CartItemUnit(
                        key=existing_unit.key,
                        quantity=(
                            existing_unit.quantity
                            - new_item.quantity
                        ),
                        base_price=existing_unit.base_price,
                        variation=existing_unit.variation
                    )
                )

            elif existing_unit.quantity == new_item.quantity:

                # Remove this variation completely.
                pass

            else:

                # Do not remove more than exists.
                updated_units.append(existing_unit)

        if unit_found:
            item_found = True

        if updated_units:

            updated_items.append(
                CartItem(
                    item_id=existing_item.item_id,
                    title=existing_item.title,
                    units=updated_units
                )
            )

        elif not unit_found:

            updated_items.append(existing_item)

    # ---------------------------------------------------------
    # 5. Validate that requested item existed
    # ---------------------------------------------------------
    if not item_found:
        return _failure(
            f"Item {title} not found in cart.",
            tool_call_id
        )

    updated_cart = Cart(
        items=updated_items
    )

    return Command(
        update={
            "cart": updated_cart,
            "order_confirmation_pending": False,
            "finished": False,
            "messages": [
                ToolMessage(
                    f"Removed {title} from cart",
                    tool_call_id=tool_call_id
                )
            ]
        }
    )


@tool
def clear_cart(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[OrderState, InjectedState]
):
    """Clear all items from the current cart."""

    return Command(
        update={
            "cart": Cart(items=[]),
            "order_confirmation_pending": False,
            "finished": False,
            "messages": [
                ToolMessage(
                    "Cart cleared successfully.",
                    tool_call_id=tool_call_id
                )
            ]
        }
    )


@tool
def confirm_order(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[OrderState, InjectedState],
):
    """
    Prepare the current cart for final customer confirmation.

    This tool does NOT place the order.
    """

    cart = state.get("cart")

    if cart is None or not cart.items:

        return _failure(
            "Cannot confirm an empty cart. Please add items first.",
            tool_call_id
        )

    item_lines = []
    total = 0.0

    try:

        for item in cart.items:

            for unit in item.units:

                if (
                    not _valid_quantity(unit.quantity)
                    or not _valid_price(unit.base_price)
                ):
                    raise ValueError(
                        "Cart contains invalid quantity or price."
                    )

                line_total = (
                    unit.quantity
                    * unit.base_price
                )

                total += line_total

                variation_text = ""

                if unit.variation is not None:
                    variation_text = (
                        f" ({unit.variation.name})"
                    )

                item_lines.append(
                    f"- {item.title}{variation_text} "
                    f"× {unit.quantity} — ₹{line_total:g}"
                )

    except (AttributeError, TypeError, ValueError):

        return _failure(
            "Cannot confirm the order because the cart contains invalid items.",
            tool_call_id
        )

    return Command(
        update={
            "order_confirmation_pending": True,
            "messages": [
                ToolMessage(
                    "Order summary:\n"
                    + "\n".join(item_lines)
                    + f"\n\nTotal: ₹{total:g}",
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


@tool
def get_cart(
    state: Annotated[OrderState, InjectedState]
):
    """Provide the latest items in the cart."""
    return state["cart"]


@tool
def place_order(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[OrderState, InjectedState],
):
    """
    Place the current cart order after explicit customer confirmation.
    """

    current_cart = state.get("cart")
    log_event(
        logger,
        "agent_checkout.validation_started",
        authenticated=state.get("user_id") is not None,
        cart_line_count=len(current_cart.items) if current_cart is not None else 0,
    )

    # ---------------------------------------------------------
    # 1. Require confirm_order
    # ---------------------------------------------------------
    if not state.get("order_confirmation_pending", False):
        return _failure(
            "Order confirmation is required before placing the order. "
            "Please review and confirm the cart first.",
            tool_call_id
        )

    # ---------------------------------------------------------
    # 2. Require an explicit human confirmation message
    #
    # A model can otherwise call confirm_order and place_order
    # consecutively in the same graph turn. Require the latest
    # human message to be an explicit affirmative response.
    # ---------------------------------------------------------
    latest_human_message = None

    for message in reversed(state.get("messages", [])):

        if isinstance(message, HumanMessage):

            latest_human_message = message
            break

    if latest_human_message is None:

        return _failure(
            "Please explicitly confirm the order before placing it.",
            tool_call_id
        )

    confirmation_text = (
        latest_human_message.content
        if isinstance(latest_human_message.content, str)
        else str(latest_human_message.content)
    ).strip().lower()

    affirmative_responses = {
        "yes",
        "yes please",
        "yes, please",
        "confirm",
        "confirm order",
        "confirmed",
        "confirmed",
        "yes, confirm",
        "yes, confirm the order",
        "proceed",
        "proceed with the order",
        "i confirm",
        "i confirm the order",
        "looks good",
        "looks good, place it",
        "that's correct",
        "that is correct",
        "correct",
    }

    if confirmation_text not in affirmative_responses:

        return _failure(
            "Please explicitly confirm the order before placing it.",
            tool_call_id
        )

    # ---------------------------------------------------------
    # 3. Validate current cart
    #
    # We intentionally do NOT block based on an old orderId.
    # A previous confirmed order can remain available for status
    # lookup while a newly populated cart starts a new order.
    # ---------------------------------------------------------
    if current_cart is None or not current_cart.items:
        log_event(
            logger,
            "agent_checkout.validation_failed",
            level=logging.WARNING,
            reason_code="empty_cart",
            authenticated=state.get("user_id") is not None,
        )

        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "Cannot place order. Cart is empty. "
                        "Please add items to your cart first.",
                        tool_call_id=tool_call_id
                    )
                ]
            }
        )

    # ---------------------------------------------------------
    # 4. Build authoritative order items
    # ---------------------------------------------------------
    order_items = []

    try:

        for cart_item in current_cart.items:

            if not cart_item.item_id or not cart_item.title:
                raise ValueError("Cart item is malformed")

            for unit in cart_item.units:

                if (
                    not _valid_quantity(unit.quantity)
                    or not _valid_price(unit.base_price)
                ):
                    raise ValueError(
                        "Cart item has invalid quantity or price"
                    )

                order_items.append(
                    {
                        "item_id": cart_item.item_id,
                        "title": cart_item.title,
                        "quantity": unit.quantity,
                        "base_price": unit.base_price,
                        "variation": (
                            unit.variation.model_dump()
                            if unit.variation
                            else None
                        ),
                    }
                )

    except (AttributeError, TypeError, ValueError):

        return _failure(
            "Cannot place order because the cart contains invalid items.",
            tool_call_id
        )

    if not order_items:

        return _failure(
            "Cannot place order. Cart is empty. "
            "Please add items to your cart first.",
            tool_call_id
        )

    # ---------------------------------------------------------
    # 5. Send order to menu backend
    # ---------------------------------------------------------
    order_url = (
        f"{config.MENU_BACKEND_URL.rstrip('/')}/orders"
    )

    payload = {
        "restaurant_name": state["restaurant_name"],
        "subdomain": state["subdomain"],
        "user_id": str(state.get("user_id") or ""),
        "items": order_items,
    }

    user_id = state.get("user_id")
    if user_id is None or not str(user_id).strip():
        log_event(
            logger,
            "agent_checkout.validation_failed",
            level=logging.WARNING,
            reason_code="authentication_required",
            authenticated=False,
        )
        return _failure("An authenticated user is required before placing an order.", tool_call_id)
    intent_fingerprint = fingerprint(payload)
    idempotency_key = "agent-" + hashlib.sha256(
        f"{user_id}:{state.get('orderId') or 'new'}:{intent_fingerprint}".encode("utf-8")
    ).hexdigest()

    try:
        result, total_items = _place_order_with_outbox(
            payload=payload,
            idempotency_key=idempotency_key,
            order_url=order_url,
        )
        if (
            not isinstance(result, dict)
            or not _valid_order_id(result.get("order_id"))
            or result.get("status") != "confirmed"
            or not _valid_price(result.get("subtotal"))
        ):
            raise ValueError("Order service response is invalid")
        order_id = result["order_id"]
        status = result["status"]
        subtotal = result["subtotal"]
        return Command(
            update={
                "cart": Cart(items=[]),
                "orderId": order_id,
                "order_status": status,
                "order_history_persisted": True,
                "order_confirmation_pending": False,
                "finished": True,
                "messages": [
                    ToolMessage(
                        f"Order {order_id} confirmed! Total: {subtotal}. "
                        f"Total items: {total_items}. Thank you for your order!",
                        tool_call_id=tool_call_id,
                    )
                ],
            }
        )
    except requests.Timeout:
        error_message = (
            "The ordering service timed out before confirming the order. "
            "Your cart is still saved. Please retry the same confirmation; "
            "the checkout intent will be reused."
        )
    except requests.ConnectionError:
        error_message = (
            "The ordering service is unavailable, so the order is not confirmed. "
            "Your cart is still saved. Please retry the same confirmation; "
            "the checkout intent will be reused."
        )
    except requests.RequestException:
        error_message = (
            "The ordering service could not confirm the order. Your cart is still saved. "
            "Please retry the same confirmation or contact support."
        )
    except OperationConflict:
        error_message = (
            "This checkout request conflicts with an earlier request, so I cannot "
            "confirm it. Your cart is still saved. Please contact support before retrying."
        )
    except Exception:
        error_message = (
            "The ordering service may have accepted the order, but its confirmation "
            "could not be saved. Your cart is still saved while the same checkout "
            "intent is reconciled. Please retry the same confirmation; do not start a new order."
        )

    # ---------------------------------------------------------
    # 6. Return API failure without corrupting existing state
    # ---------------------------------------------------------
    return Command(
        update={
            "messages": [
                ToolMessage(
                    error_message,
                    tool_call_id=tool_call_id
                )
            ]
        }
    )
