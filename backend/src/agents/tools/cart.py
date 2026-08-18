import requests
from src.configs.config import config
from langchain_core.tools import tool, InjectedToolCallId
from langgraph.types import Command
from langchain_core.messages import ToolMessage
from pprint import pprint
from typing import List, Annotated
from src.agents.state import CartItemUnit, Cart, CartItem, OrderState
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
    return Command(update={"messages": [ToolMessage(message, tool_call_id=tool_call_id)]})


def _valid_quantity(quantity: object) -> bool:
    return isinstance(quantity, int) and not isinstance(quantity, bool) and quantity > 0


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
def add_cart(item_id: str, title: str, new_item: CartItemUnit, tool_call_id: Annotated[str, InjectedToolCallId], state: Annotated[OrderState, InjectedState]):
    """
    Adds an item to the cart

    Args:
    item_id : Unique UUID for the item
    title: Title of the item
    new_item: Cart item details with base_price, quantity, and variation (only if the item has variants like Full/Half)
    """

    if not _valid_quantity(new_item.quantity):
        return _failure("Quantity must be greater than zero.", tool_call_id)

    items, error = _fetch_menu_items(state)
    if error:
        return _failure(f"Cannot add item: {error}", tool_call_id)

    menu_item = next((item for item in items if item.get("id") == item_id), None)
    if menu_item is None or menu_item.get("title") != title:
        return _failure("That item is not available on the current menu.", tool_call_id)
    authoritative_price = menu_item.get("base_price")
    if not _valid_price(authoritative_price):
        return _failure("That menu item has invalid pricing and cannot be added.", tool_call_id)

    variation_id = "no_variant"
    valid_variation = None
    if new_item.variation is not None:
        variation_id = new_item.variation.id.strip()
        variations = menu_item.get("variations", [])
        if not variation_id or not isinstance(variations, list):
            return _failure("That item variation is not available on the current menu.", tool_call_id)
        if not any(isinstance(variation, dict) and variation.get("id") == variation_id for variation in variations):
            return _failure("That item variation is not available on the current menu.", tool_call_id)
        valid_variation = new_item.variation

    item_key = f"{item_id}|{variation_id}"

    # Create a proper CartItemUnit with the key
    updated_unit = CartItemUnit(
        key=item_key,
        quantity=new_item.quantity,
        base_price=authoritative_price,
        variation=valid_variation
    )

    # Get current cart
    current_cart = state["cart"]
    if current_cart is None:
        # If cart is None, create new cart with this item
        new_cart_item = CartItem(
            item_id=item_id,
            title=title,
            units=[updated_unit]
        )
        updated_cart = Cart(items=[new_cart_item])
    else:
        # Check if item already exists in cart
        item_found = False
        updated_items = []

        for existing_item in current_cart.items:
            if existing_item.item_id == item_id:
                # Item exists, check if this specific variant exists
                unit_found = False
                updated_units = []

                for existing_unit in existing_item.units:
                    if existing_unit.key == item_key:
                        # Same variant exists, increment quantity
                        updated_units.append(CartItemUnit(
                            key=existing_unit.key,
                            quantity=existing_unit.quantity + new_item.quantity,
                            base_price=existing_unit.base_price,
                            variation=existing_unit.variation
                        ))
                        unit_found = True
                    else:
                        updated_units.append(existing_unit)

                if not unit_found:
                    # New variant of existing item
                    updated_units.append(updated_unit)

                updated_items.append(CartItem(
                    item_id=existing_item.item_id,
                    title=existing_item.title,
                    units=updated_units
                ))
                item_found = True
            else:
                updated_items.append(existing_item)

        if not item_found:
            # Completely new item
            new_cart_item = CartItem(
                item_id=item_id,
                title=title,
                units=[updated_unit]
            )
            updated_items.append(new_cart_item)

        updated_cart = Cart(items=updated_items)

    return Command(update={
        "cart": updated_cart,
        "order_confirmation_pending": False,
        "messages": [
            ToolMessage(
                f"Added {title} to cart", tool_call_id=tool_call_id)
        ]
    })


@tool
def remove_from_cart(item_id: str, title: str, new_item: CartItemUnit, tool_call_id: Annotated[str, InjectedToolCallId], state: Annotated[OrderState, InjectedState]):
    """
    Removes an item from the cart

    Args:
    item_id : Unique UUID for the item
    title: Title of the item
    new_item: A dict containing base_price and quantity of the item to remove
    """

    if not _valid_quantity(new_item.quantity):
        return _failure("Quantity must be greater than zero.", tool_call_id)

    # Handle variation ID safely
    variation_id = "no_variant"
    if new_item.variation:
        variation_id = new_item.variation.id.strip()
        if not variation_id:
            return _failure("A valid variation ID is required.", tool_call_id)

    item_key = f"{item_id}|{variation_id}"

    # Get current cart
    current_cart = state["cart"]
    if current_cart is None or not current_cart.items:
        return Command(update={
            "messages": [
                ToolMessage(
                    f"Cart is empty. Cannot remove {title}.", tool_call_id=tool_call_id)
            ]
        })

    # Find and remove the item
    updated_items = []
    item_found = False
    removal_message = f"Item {title} not found in cart."

    for existing_item in current_cart.items:
        if existing_item.item_id == item_id:
            # Item exists, check if this specific variant exists
            unit_found = False
            updated_units = []

            for existing_unit in existing_item.units:
                if existing_unit.key == item_key:
                    # Found the variant to remove
                    unit_found = True
                    if existing_unit.quantity > new_item.quantity:
                        # Reduce quantity
                        updated_units.append(CartItemUnit(
                            key=existing_unit.key,
                            quantity=existing_unit.quantity - new_item.quantity,
                            base_price=existing_unit.base_price,
                            variation=existing_unit.variation
                        ))
                        removal_message = f"Reduced {title} quantity by {new_item.quantity}"
                    elif existing_unit.quantity == new_item.quantity:
                        # Remove this variant completely (don't add to updated_units)
                        removal_message = f"Removed {title} from cart"
                    else:
                        # Trying to remove more than available
                        updated_units.append(existing_unit)
                        removal_message = f"Cannot remove {new_item.quantity} {title}. Only {existing_unit.quantity} available."
                else:
                    # Keep other variants
                    updated_units.append(existing_unit)

            if unit_found:
                item_found = True
                if updated_units:
                    # Still has other variants, keep the item
                    updated_items.append(CartItem(
                        item_id=existing_item.item_id,
                        title=existing_item.title,
                        units=updated_units
                    ))
                # If no units left, item is completely removed (don't add to updated_items)
            else:
                # Variant not found, keep original item
                updated_items.append(existing_item)
                removal_message = f"Variant of {title} not found in cart."
        else:
            # Different item, keep it
            updated_items.append(existing_item)

    if not item_found:
        # Item ID not found at all
        updated_cart = current_cart
    else:
        # Update cart with remaining items
        updated_cart = Cart(items=updated_items)

    return Command(update={
        "cart": updated_cart,
        "order_confirmation_pending": False,
        "messages": [
            ToolMessage(removal_message, tool_call_id=tool_call_id)
        ]
    })

@tool
def clear_cart(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[OrderState, InjectedState]
):
    """Clear all items from the customer's cart."""

    return Command(update={
        "cart": Cart(items=[]),
        "order_confirmation_pending": False,
        "messages": [
            ToolMessage(
                "Cart cleared successfully.",
                tool_call_id=tool_call_id
            )
        ]
    })


@tool
def confirm_order(
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[OrderState, InjectedState],
):
    """Show the current cart summary before placing an order."""
    cart = state.get("cart")
    if cart is None or not cart.items:
        return _failure("Cart is empty. Add items before placing an order.", tool_call_id)

    item_lines = []
    total = 0.0
    for item in cart.items:
        for unit in item.units:
            line_total = unit.quantity * unit.base_price
            total += line_total
            item_lines.append(f"- {item.title} × {unit.quantity} — ₹{line_total:g}")

    return Command(update={
        "order_confirmation_pending": True,
        "messages": [
            ToolMessage(
                "Order summary:\n" + "`r`n".join(item_lines) + f"`r`n`r`nTotal: ₹{total:g}",
                tool_call_id=tool_call_id,
            )
        ],
    })

@tool
def get_cart(state: Annotated[OrderState, InjectedState]):
    """Provide the lastest items in the cart"""
    # print("Input State", state)
    return state['cart']


@tool
def place_order(tool_call_id: Annotated[str, InjectedToolCallId], state: Annotated[OrderState, InjectedState]):
    """Place the order and complete the ordering process"""

    current_cart = state['cart']

    if state.get("orderId") and state.get("order_status") == "confirmed":
        return _failure(
            "An order is already confirmed for this session. Check or cancel it before placing another order.",
            tool_call_id,
        )

    # Check if cart is empty
    if current_cart is None or not current_cart.items:
        return Command(update={
            "messages": [
                ToolMessage(
                    "Cannot place order. Cart is empty. Please add items to your cart first.",
                    tool_call_id=tool_call_id
                )
            ]
        })

    order_items = []
    try:
        for cart_item in current_cart.items:
            if not cart_item.item_id or not cart_item.title:
                raise ValueError("Cart item is malformed")
            for unit in cart_item.units:
                if not _valid_quantity(unit.quantity) or not _valid_price(unit.base_price):
                    raise ValueError("Cart item has invalid quantity or price")
                order_items.append({
                    "item_id": cart_item.item_id,
                    "title": cart_item.title,
                    "quantity": unit.quantity,
                    "base_price": unit.base_price,
                    "variation": unit.variation.model_dump() if unit.variation else None,
                })
    except (AttributeError, TypeError, ValueError):
        return _failure("Cannot place order because the cart contains invalid items.", tool_call_id)

    if not order_items:
        return _failure("Cannot place order. Cart is empty. Please add items to your cart first.", tool_call_id)

    order_url = f"{config.MENU_BACKEND_URL.rstrip('/')}/orders"
    payload = {
        "restaurant_name": state["restaurant_name"],
        "subdomain": state["subdomain"],
        "items": order_items,
    }

    try:
        response = requests.post(order_url, json=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("Order API response is malformed")
        order_id = result.get("order_id")
        status = result.get("status")
        subtotal = result.get("subtotal")
        if not isinstance(order_id, str) or not order_id or status != "confirmed":
            raise ValueError("Order API response did not include a valid order_id")
        if not _valid_price(subtotal):
            raise ValueError("Order API response included an invalid subtotal")
    except requests.Timeout:
        error_message = "Unable to place order: the ordering service timed out. Please try again."
    except requests.ConnectionError:
        error_message = "Unable to place order: the ordering service is unavailable. Please try again."
    except requests.RequestException as exc:
        error_message = f"Unable to place order: the ordering service returned an error ({exc})."
    except (ValueError, TypeError, AttributeError):
        error_message = "Unable to place order: the ordering service returned an invalid response."
    else:
        total_items = sum(item["quantity"] for item in order_items)
        return Command(update={
            "cart": Cart(items=[]),
            "orderId": order_id,
            "order_status": status,
            "order_confirmation_pending": False,
            "finished": True,
            "messages": [
                ToolMessage(
                    f"Order {order_id} confirmed! Total: {subtotal}. "
                    f"Total items: {total_items}. Thank you for your order!",
                    tool_call_id=tool_call_id
                )
            ]
        })

    # On every API failure, deliberately omit cart/order state updates.
    return Command(update={
        "messages": [
            ToolMessage(
                error_message,
                tool_call_id=tool_call_id
            )
        ]
    })

