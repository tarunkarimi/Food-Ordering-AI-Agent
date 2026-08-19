import requests
from src.configs.config import config
from langchain_core.tools import tool, InjectedToolCallId
from langgraph.types import Command
from langchain_core.messages import ToolMessage
from typing import Annotated
from src.agents.state import (
    CartItemUnit,
    Cart,
    CartItem,
    OrderState,
    ItemVariation,
)
from langgraph.prebuilt import InjectedState


def _menu_url(subdomain: str) -> str:
    return f"{config.MENU_BACKEND_URL.rstrip('/')}/?subdomain={subdomain}"


def _fetch_menu_items(state: OrderState) -> tuple[list[dict], str | None]:
    """Fetch and minimally validate the authoritative tenant menu."""
    try:
        response = requests.get(_menu_url(state["subdomain"]), timeout=10)
        response.raise_for_status()
        menu = response.json()

        if not isinstance(menu, dict) or not isinstance(menu.get("items"), list):
            raise ValueError("Menu response is malformed")

        items = menu["items"]

        if not all(isinstance(item, dict) for item in items):
            raise ValueError("Menu response is malformed")

        return items, None

    except requests.Timeout:
        return [], "The menu service timed out. Please try again."

    except requests.ConnectionError:
        return [], "The menu service is unavailable. Please try again."

    except requests.RequestException:
        return [], "The menu service returned an error. Please try again."

    except (ValueError, TypeError, AttributeError):
        return [], "The menu service returned an invalid response. Please try again."


def _failure(message: str, tool_call_id: str) -> Command:
    return Command(
        update={
            "messages": [
                ToolMessage(message, tool_call_id=tool_call_id)
            ]
        }
    )


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

        valid_variation = ItemVariation(
            id=menu_variation["id"],
            name=str(menu_variation.get("name", "")),
            price=str(
                menu_variation.get(
                    "price",
                    authoritative_price
                )
            )
        )

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
                                base_price=existing_unit.base_price,
                                variation=existing_unit.variation
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
    """

    if not _valid_quantity(new_item.quantity):
        return _failure(
            "Quantity must be greater than zero.",
            tool_call_id
        )

    # Handle variation ID safely.
    variation_id = "no_variant"

    if new_item.variation:
        variation_id = new_item.variation.id.strip()

        if not variation_id:
            return _failure(
                "A valid variation ID is required.",
                tool_call_id
            )

    item_key = f"{item_id}|{variation_id}"

    current_cart = state["cart"]

    if current_cart is None or not current_cart.items:

        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f"Cart is empty. Cannot remove {title}.",
                        tool_call_id=tool_call_id
                    )
                ]
            }
        )

    updated_items = []
    item_found = False
    removal_message = f"Item {title} not found in cart."

    for existing_item in current_cart.items:

        if existing_item.item_id == item_id:

            unit_found = False
            updated_units = []

            for existing_unit in existing_item.units:

                if existing_unit.key == item_key:

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

                        removal_message = (
                            f"Reduced {title} quantity "
                            f"by {new_item.quantity}"
                        )

                    elif existing_unit.quantity == new_item.quantity:

                        removal_message = (
                            f"Removed {title} from cart"
                        )

                    else:

                        updated_units.append(existing_unit)

                        removal_message = (
                            f"Cannot remove {new_item.quantity} "
                            f"{title}. Only "
                            f"{existing_unit.quantity} available."
                        )

                else:

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

            else:

                updated_items.append(existing_item)

                removal_message = (
                    f"Variant of {title} not found in cart."
                )

        else:

            updated_items.append(existing_item)

    if not item_found:
        updated_cart = current_cart
    else:
        updated_cart = Cart(items=updated_items)

    return Command(
        update={
            "cart": updated_cart,
            "order_confirmation_pending": False,
            "messages": [
                ToolMessage(
                    removal_message,
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
    """Clear all items from the customer's cart."""

    return Command(
        update={
            "cart": Cart(items=[]),
            "order_confirmation_pending": False,
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
    """Show the current cart summary before placing an order."""

    cart = state.get("cart")

    if cart is None or not cart.items:
        return _failure(
            "Cart is empty. Add items before placing an order.",
            tool_call_id
        )

    item_lines = []
    total = 0.0

    for item in cart.items:

        for unit in item.units:

            line_total = unit.quantity * unit.base_price
            total += line_total

            item_lines.append(
                f"- {item.title} × {unit.quantity} — ₹{line_total:g}"
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
    state: Annotated[OrderState, InjectedState]
):
    """Place the order and complete the ordering process."""

    current_cart = state["cart"]

    if (
        state.get("orderId")
        and state.get("order_status") == "confirmed"
    ):
        return _failure(
            "An order is already confirmed for this session. "
            "Check or cancel it before placing another order.",
            tool_call_id
        )

    if current_cart is None or not current_cart.items:

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

    order_url = (
        f"{config.MENU_BACKEND_URL.rstrip('/')}/orders"
    )

    payload = {
        "restaurant_name": state["restaurant_name"],
        "subdomain": state["subdomain"],
        "items": order_items,
    }

    try:

        response = requests.post(
            order_url,
            json=payload,
            timeout=10
        )

        response.raise_for_status()

        result = response.json()

        if not isinstance(result, dict):
            raise ValueError(
                "Order API response is malformed"
            )

        order_id = result.get("order_id")
        status = result.get("status")
        subtotal = result.get("subtotal")

        if (
            not isinstance(order_id, str)
            or not order_id
            or status != "confirmed"
        ):
            raise ValueError(
                "Order API response did not include a valid order_id"
            )

        if not _valid_price(subtotal):
            raise ValueError(
                "Order API response included an invalid subtotal"
            )

    except requests.Timeout:

        error_message = (
            "Unable to place order: the ordering service "
            "timed out. Please try again."
        )

    except requests.ConnectionError:

        error_message = (
            "Unable to place order: the ordering service "
            "is unavailable. Please try again."
        )

    except requests.RequestException as exc:

        error_message = (
            "Unable to place order: the ordering service "
            f"returned an error ({exc})."
        )

    except (ValueError, TypeError, AttributeError):

        error_message = (
            "Unable to place order: the ordering service "
            "returned an invalid response."
        )

    else:

        total_items = sum(
            item["quantity"]
            for item in order_items
        )

        return Command(
            update={
                "cart": Cart(items=[]),
                "orderId": order_id,
                "order_status": status,
                "order_confirmation_pending": False,
                "finished": True,
                "messages": [
                    ToolMessage(
                        f"Order {order_id} confirmed! "
                        f"Total: {subtotal}. "
                        f"Total items: {total_items}. "
                        "Thank you for your order!",
                        tool_call_id=tool_call_id
                    )
                ]
            }
        )

    # On every API failure, deliberately omit cart/order state updates.
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