"""Authenticated reorder service."""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.agents.tools.cart import _fetch_menu_items, _valid_price, _valid_quantity
from src.db.models import CartItem, OrderHistory
from src.services.cart import get_or_create_cart


def get_reorder_items(
    db: Session,
    *,
    user_id: int,
    order_id: str,
) -> dict[str, Any]:
    """Return a historical order snapshot suitable for reorder processing."""

    normalized_order_id = order_id.strip()

    if not normalized_order_id:
        raise ValueError("Order ID is required.")

    order = db.scalar(
        select(OrderHistory).where(
            OrderHistory.user_id == user_id,
            OrderHistory.order_id == normalized_order_id,
        )
    )

    if order is None:
        raise LookupError("Order not found.")

    try:
        items = json.loads(order.items_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(
            "Order history contains invalid item data."
        ) from exc

    if not isinstance(items, list) or not items:
        raise ValueError("Order history contains no reorderable items.")

    if not all(isinstance(item, dict) for item in items):
        raise ValueError("Order history contains invalid item data.")

    return {
        "order_id": order.order_id,
        "restaurant_name": order.restaurant_name,
        "subdomain": order.subdomain,
        "status": order.status,
        "items": items,
    }


def validate_reorder_items(
    *,
    subdomain: str,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Validate historical items against the current authoritative menu.

    Historical prices are never trusted. Current menu prices are returned.
    """

    menu_items, error = _fetch_menu_items(
        {
            "subdomain": subdomain,
        }
    )

    if error:
        raise ConnectionError(error)

    validated_items: list[dict[str, Any]] = []

    for historical_item in items:
        item_id = historical_item.get("item_id")
        title = historical_item.get("title")
        quantity = historical_item.get("quantity")

        if (
            not isinstance(item_id, str)
            or not item_id.strip()
            or not isinstance(title, str)
            or not title.strip()
        ):
            raise ValueError(
                "Order history contains an invalid menu item."
            )

        if not _valid_quantity(quantity):
            raise ValueError(
                f"Invalid quantity for '{title}'."
            )

        menu_item = next(
            (
                item
                for item in menu_items
                if (
                    isinstance(item, dict)
                    and item.get("id") == item_id
                    and item.get("title") == title
                )
            ),
            None,
        )

        if menu_item is None:
            raise LookupError(
                f"'{title}' is no longer available on the current menu."
            )

        raw_base_price = menu_item.get(
            "base_price",
            menu_item.get("price"),
        )

        try:
            base_price = float(raw_base_price)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"'{title}' has invalid pricing on the current menu."
            ) from exc

        if not _valid_price(base_price):
            raise ValueError(
                f"'{title}' has invalid pricing on the current menu."
            )

        variations = menu_item.get("variations", [])

        if not isinstance(variations, list):
            raise ValueError(
                f"'{title}' has invalid variation data on the current menu."
            )

        historical_variation = historical_item.get("variation")

        if historical_variation is not None:
            if not isinstance(historical_variation, dict):
                raise ValueError(
                    f"'{title}' has invalid historical variation data."
                )

            historical_variation_id = historical_variation.get("id")

            if (
                not isinstance(historical_variation_id, str)
                or not historical_variation_id.strip()
            ):
                raise ValueError(
                    f"'{title}' has invalid historical variation data."
                )

            current_variation = next(
                (
                    variation
                    for variation in variations
                    if (
                        isinstance(variation, dict)
                        and variation.get("id") == historical_variation_id
                    )
                ),
                None,
            )

            if current_variation is None:
                raise LookupError(
                    f"The selected variation for '{title}' "
                    "is no longer available on the current menu."
                )

            raw_variation_price = current_variation.get(
                "price",
                base_price,
            )

            try:
                variation_price = float(raw_variation_price)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"The selected variation for '{title}' "
                    "has invalid pricing on the current menu."
                ) from exc

            if not _valid_price(variation_price):
                raise ValueError(
                    f"The selected variation for '{title}' "
                    "has invalid pricing on the current menu."
                )

            validated_items.append(
                {
                    "item_key": (
                        f"{item_id.strip()}|"
                        f"{historical_variation_id.strip()}"
                    ),
                    "item_id": item_id.strip(),
                    "title": title.strip(),
                    "quantity": quantity,
                    "unit_price": variation_price,
                    "variation_id": historical_variation_id.strip(),
                    "variation_name": str(
                        current_variation.get("name", "")
                    ).strip(),
                    "variation_price": variation_price,
                    "base_price": variation_price,
                    "variation": {
                        "id": current_variation["id"],
                        "name": str(
                            current_variation.get("name", "")
                        ).strip(),
                        "price": variation_price,
                    },
                }
            )
            continue

        if variations:
            raise LookupError(
                f"'{title}' now requires a menu variation."
            )

        validated_items.append(
            {
                "item_key": f"{item_id.strip()}|no_variant",
                "item_id": item_id.strip(),
                "title": title.strip(),
                "quantity": quantity,
                "unit_price": base_price,
                "variation_id": None,
                "variation_name": None,
                "variation_price": None,
                "base_price": base_price,
                "variation": None,
            }
        )

    return validated_items


def add_reorder_items_to_cart(
    db: Session,
    *,
    user_id: int,
    restaurant_name: str,
    subdomain: str,
    items: list[dict[str, Any]],
):
    """Add validated reorder items to the user's persistent cart.

    All items are validated before this function is called. Historical
    prices are therefore never written into the cart.
    """

    cart = get_or_create_cart(
        db,
        user_id=user_id,
        restaurant_name=restaurant_name,
        subdomain=subdomain,
    )

    existing_by_key = {
        item.item_key: item
        for item in cart.items
    }

    for item in items:
        item_key = item["item_key"]

        existing = existing_by_key.get(item_key)

        if existing is None:
            db.add(
                CartItem(
                    cart=cart,
                    item_key=item_key,
                    item_id=item["item_id"],
                    title=item["title"],
                    quantity=item["quantity"],
                    unit_price=item["unit_price"],
                    variation_id=item["variation_id"],
                    variation_name=item["variation_name"],
                    variation_price=item["variation_price"],
                )
            )
            continue

        existing.quantity += item["quantity"]
        existing.title = item["title"]
        existing.unit_price = item["unit_price"]
        existing.variation_name = item["variation_name"]
        existing.variation_price = item["variation_price"]

    db.commit()

    return cart.__class__.query if False else _reload_cart(db, user_id)


def _reload_cart(db: Session, user_id: int):
    """Reload the cart with its items after the transaction."""

    from src.services.cart import get_cart

    return get_cart(
        db,
        user_id=user_id,
    )
