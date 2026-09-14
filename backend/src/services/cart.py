"""Persistent authenticated-cart service."""

from decimal import Decimal

from sqlalchemy.orm import Session

from src.db.models import Cart
from src.repositories.cart_repository import (
    add_cart_item,
    create_cart,
    delete_all_cart_items,
    delete_cart_item,
    get_cart as repository_get_cart,
    get_cart_item,
)


def get_or_create_cart(
    db: Session,
    *,
    user_id: int,
    restaurant_name: str,
    subdomain: str,
) -> Cart:
    """Return the user's cart, creating or switching an empty cart as needed."""
    cart = repository_get_cart(db, user_id=user_id)

    if cart is None:
        return create_cart(
            db,
            user_id=user_id,
            restaurant_name=restaurant_name,
            subdomain=subdomain,
        )

    if (
        cart.restaurant_name != restaurant_name
        or cart.subdomain != subdomain
    ):
        if cart.items:
            raise ValueError(
                "Your cart belongs to another restaurant. "
                "Please clear the existing cart before switching restaurants."
            )

        cart.restaurant_name = restaurant_name
        cart.subdomain = subdomain

    return cart


def get_cart(
    db: Session,
    *,
    user_id: int,
) -> Cart | None:
    """Return a user's persistent cart."""
    return repository_get_cart(db, user_id=user_id)


def add_item(
    db: Session,
    *,
    user_id: int,
    restaurant_name: str,
    subdomain: str,
    item_key: str,
    item_id: str,
    title: str,
    quantity: int,
    unit_price: float,
    variation_id: str | None,
    variation_name: str | None,
    variation_price: float | None,
) -> Cart:
    """Add an item to the user's persistent cart."""
    cart = get_or_create_cart(
        db,
        user_id=user_id,
        restaurant_name=restaurant_name,
        subdomain=subdomain,
    )

    existing = get_cart_item(
        cart,
        item_key=item_key,
    )

    if existing is None:
        add_cart_item(
            db,
            cart=cart,
            item_key=item_key,
            item_id=item_id,
            title=title,
            quantity=quantity,
            unit_price=unit_price,
            variation_id=variation_id,
            variation_name=variation_name,
            variation_price=variation_price,
        )
    else:
        existing.quantity += quantity
        existing.title = title
        existing.unit_price = unit_price
        existing.variation_name = variation_name
        existing.variation_price = variation_price

    db.commit()

    return get_cart(db, user_id=user_id)


def update_item(
    db: Session,
    *,
    user_id: int,
    item_key: str,
    quantity: int,
    unit_price: float,
    title: str,
    variation_name: str | None,
    variation_price: float | None,
) -> Cart:
    """Update an existing persistent cart item."""
    cart = get_cart(db, user_id=user_id)

    if cart is None:
        raise LookupError("Cart not found.")

    item = get_cart_item(
        cart,
        item_key=item_key,
    )

    if item is None:
        raise LookupError("Cart item not found.")

    item.quantity = quantity
    item.unit_price = unit_price
    item.title = title
    item.variation_name = variation_name
    item.variation_price = variation_price

    db.commit()

    return get_cart(db, user_id=user_id)


def remove_item(
    db: Session,
    *,
    user_id: int,
    item_key: str,
) -> Cart:
    """Remove one item from the persistent cart."""
    cart = get_cart(db, user_id=user_id)

    if cart is None:
        raise LookupError("Cart not found.")

    item = get_cart_item(
        cart,
        item_key=item_key,
    )

    if item is None:
        raise LookupError("Cart item not found.")

    delete_cart_item(
        db,
        item=item,
    )
    db.commit()

    return get_cart(db, user_id=user_id)


def clear_cart(
    db: Session,
    *,
    user_id: int,
) -> Cart | None:
    """Remove all items from a user's persistent cart."""
    cart = get_cart(db, user_id=user_id)

    if cart is None:
        return None

    delete_all_cart_items(
        db,
        cart=cart,
    )
    db.commit()

    return get_cart(db, user_id=user_id)


def cart_total(cart: Cart | None) -> Decimal:
    """Calculate the total value of a persistent cart."""
    if cart is None:
        return Decimal("0.00")

    return sum(
        (
            Decimal(str(item.unit_price)) * item.quantity
            for item in cart.items
        ),
        Decimal("0.00"),
    )
