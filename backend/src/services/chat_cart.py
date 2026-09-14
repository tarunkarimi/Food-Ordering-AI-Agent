"""Conversation and cart domain services."""

from typing import Optional

from src.agents.state import Cart, CartItem, CartItemUnit, ItemVariation
from src.agents.tools.cart import _valid_price, _valid_quantity


def build_session_config(
    session_id: str,
    user_id: Optional[int] = None,
) -> dict:
    """Build a user-isolated LangGraph thread configuration."""
    clean_session_id = session_id.strip()

    if user_id is None:
        thread_id = clean_session_id
    else:
        thread_id = f"user:{user_id}:session:{clean_session_id}"

    return {
        "configurable": {
            "thread_id": thread_id,
        }
    }


def find_menu_item(
    items: list[dict],
    item_id: str,
    title: str,
) -> Optional[dict]:
    """Find the exact requested item from the authoritative menu."""
    return next(
        (
            item
            for item in items
            if item.get("id") == item_id
            and item.get("title") == title
        ),
        None,
    )


def build_authoritative_unit(
    menu_item: dict,
    item_id: str,
    quantity: int,
    variation_id: Optional[str],
) -> CartItemUnit:
    """Build a cart unit using authoritative menu pricing."""
    authoritative_price = menu_item.get("base_price")

    if not _valid_quantity(quantity):
        raise ValueError("Quantity must be greater than zero.")

    if not _valid_price(authoritative_price):
        raise ValueError(
            "That menu item has invalid pricing and cannot be added."
        )

    variations = menu_item.get("variations", [])

    if not isinstance(variations, list):
        raise ValueError(
            "That item has invalid variation data on the current menu."
        )

    selected_variation_id = "no_variant"
    selected_variation = None
    cart_unit_price = authoritative_price

    if variations:
        if not variation_id:
            raise ValueError(
                "Please specify a valid variation for this item."
            )

        selected_variation_id = variation_id.strip()

        if not selected_variation_id:
            raise ValueError("A valid variation ID is required.")

        menu_variation = next(
            (
                variation
                for variation in variations
                if (
                    isinstance(variation, dict)
                    and variation.get("id") == selected_variation_id
                )
            ),
            None,
        )

        if menu_variation is None:
            raise ValueError(
                "That item variation is not available on the current menu."
            )

        raw_variation_price = menu_variation.get(
            "price",
            authoritative_price,
        )

        try:
            variation_price = float(raw_variation_price)
        except (TypeError, ValueError):
            raise ValueError(
                "That item variation has invalid pricing on the current menu."
            )

        if not _valid_price(variation_price):
            raise ValueError(
                "That item variation has invalid pricing on the current menu."
            )

        selected_variation = ItemVariation(
            id=menu_variation["id"],
            name=str(menu_variation.get("name", "")),
            price=str(raw_variation_price),
        )

        cart_unit_price = variation_price

    item_key = f"{item_id}|{selected_variation_id}"

    return CartItemUnit(
        key=item_key,
        quantity=quantity,
        base_price=cart_unit_price,
        variation=selected_variation,
    )


def add_to_cart(
    current_cart: Cart,
    menu_item: dict,
    quantity: int,
    variation_id: Optional[str],
) -> Cart:
    """Add an authoritative menu item to the current cart."""
    item_id = menu_item["id"]
    title = menu_item["title"]

    new_unit = build_authoritative_unit(
        menu_item,
        item_id,
        quantity,
        variation_id,
    )

    updated_items = []
    item_found = False

    for existing_item in current_cart.items:
        if existing_item.item_id != item_id:
            updated_items.append(existing_item)
            continue

        item_found = True
        unit_found = False
        updated_units = []

        for existing_unit in existing_item.units:
            if existing_unit.key == new_unit.key:
                unit_found = True
                updated_units.append(
                    CartItemUnit(
                        key=existing_unit.key,
                        quantity=existing_unit.quantity + quantity,
                        base_price=new_unit.base_price,
                        variation=new_unit.variation,
                    )
                )
            else:
                updated_units.append(existing_unit)

        if not unit_found:
            updated_units.append(new_unit)

        updated_items.append(
            CartItem(
                item_id=item_id,
                title=title,
                units=updated_units,
            )
        )

    if not item_found:
        updated_items.append(
            CartItem(
                item_id=item_id,
                title=title,
                units=[new_unit],
            )
        )

    return Cart(items=updated_items)


def remove_from_cart(
    current_cart: Cart,
    item_id: str,
    title: str,
    quantity: int,
    variation_id: Optional[str],
) -> Cart:
    """Remove quantity from a specific cart item/variation."""
    selected_variation_id = (
        variation_id.strip()
        if variation_id
        else "no_variant"
    )

    if not selected_variation_id:
        raise ValueError("A valid variation ID is required.")

    item_key = f"{item_id}|{selected_variation_id}"

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

            if existing_unit.quantity > quantity:
                updated_units.append(
                    CartItemUnit(
                        key=existing_unit.key,
                        quantity=existing_unit.quantity - quantity,
                        base_price=existing_unit.base_price,
                        variation=existing_unit.variation,
                    )
                )
            elif existing_unit.quantity == quantity:
                pass
            else:
                updated_units.append(existing_unit)

        if unit_found:
            item_found = True

        if updated_units:
            updated_items.append(
                CartItem(
                    item_id=existing_item.item_id,
                    title=existing_item.title,
                    units=updated_units,
                )
            )
        elif not unit_found:
            updated_items.append(existing_item)

    if not item_found:
        raise ValueError(f"Item {title} not found in cart.")

    return Cart(items=updated_items)
