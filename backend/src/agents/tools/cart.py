from langchain_core.tools import tool
import requests
from configs.config import config
from langchain_core.tools import tool, InjectedToolCallId
from langgraph.types import Command
from langchain_core.messages import ToolMessage
from pprint import pprint
from typing import List, Annotated
from agents.state import CartItemUnit, Cart, CartItem, OrderState
from langgraph.prebuilt import InjectedState


@tool
def get_menu(state: Annotated[OrderState, InjectedState]):
    """Provide the latest up-to-date menu."""

    # once you fetch the menu from backend service
    # try to convert it into LLM readable format (if possible - check this case)

    MENU_URL = f"{config.MENU_BACKEND_URL}?subdomain={state["subdomain"]}"

    response = requests.get(MENU_URL)

    if response.status_code == 200:
        menu = response.json()
        items = menu['items']
        return items
    else:
        print("Error fetching the menu")


@tool
def add_cart(item_id: str, title: str, new_item: CartItemUnit, tool_call_id: Annotated[str, InjectedToolCallId], state: Annotated[OrderState, InjectedState]):
    """
    Adds an item to the cart

    Args:
    item_id : Unique UUID for the item
    title: Title of the item
    new_item: Cart item details with base_price, quantity, and variation (only if the item has variants like Full/Half)
    """

    # Handle variation ID safely
    variation_id = "no_variant"
    valid_variation = None

    # Only process variation if it exists and has valid data
    if (new_item.variation and
        hasattr(new_item.variation, 'id') and
        new_item.variation.id and
            new_item.variation.id.strip()):
        variation_id = new_item.variation.id
        valid_variation = new_item.variation

    item_key = f"{item_id}|{variation_id}"

    # Create a proper CartItemUnit with the key
    updated_unit = CartItemUnit(
        key=item_key,
        quantity=new_item.quantity,
        base_price=new_item.base_price,
        variation=valid_variation
    )

    print(updated_unit)

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

    print("Printing cart")
    pprint(updated_cart.model_dump())

    return Command(update={
        "cart": updated_cart,
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

    # Handle variation ID safely
    variation_id = "no_variant"
    if new_item.variation and hasattr(new_item.variation, 'id'):
        variation_id = new_item.variation.id

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

    print("Cart after removal:")
    pprint(updated_cart.model_dump())

    return Command(update={
        "cart": updated_cart,
        "messages": [
            ToolMessage(removal_message, tool_call_id=tool_call_id)
        ]
    })


@tool
def clear_cart(state: Annotated[OrderState, InjectedState]):
    """Clears the entire cart and removes all the present items in the cart"""
    return


@tool
def confirm_order(state: Annotated[OrderState, InjectedState]):
    """Provide the lastest items in the cart for user to confirm"""
    return state['cart']


@tool
def get_cart(state: Annotated[OrderState, InjectedState]):
    """Provide the lastest items in the cart"""
    # print("Input State", state)
    return state['cart']


@tool
def place_order(tool_call_id: Annotated[str, InjectedToolCallId], state: Annotated[OrderState, InjectedState]):
    """Place the order and complete the ordering process"""

    current_cart = state['cart']

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

    # TODO: Call the backend API to place the order which returns an orderId for the customer
    # For now, we'll simulate with a mock order ID
    import uuid
    # Generate a short mock order ID
    mock_order_id = "ZKS" + str(uuid.uuid4())[:8]

    # Calculate total items for confirmation message
    total_items = sum(sum(unit.quantity for unit in item.units)
                      for item in current_cart.items)

    # Clear the cart after placing order
    empty_cart = Cart(items=[])

    # Update state: clear cart, set orderId, and mark as finished
    return Command(update={
        "cart": empty_cart,
        "orderId": mock_order_id,
        "finished": True,
        "messages": [
            ToolMessage(
                f"Order placed successfully! Your order ID is {mock_order_id}. "
                f"Total items: {total_items}. Thank you for your order!",
                tool_call_id=tool_call_id
            )
        ]
    })
