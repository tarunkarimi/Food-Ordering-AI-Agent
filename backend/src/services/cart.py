"""Persistent authenticated-cart service."""

from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src.db.models import Cart, CartItem


def get_or_create_cart(
    db: Session,
    *,
    user_id: int,
    restaurant_name: str,
    subdomain: str,
) -> Cart:
    cart = db.scalar(
        select(Cart)
        .options(selectinload(Cart.items))
        .where(Cart.user_id == user_id)
    )

    if cart is None:
        cart = Cart(
            user_id=user_id,
            restaurant_name=restaurant_name,
            subdomain=subdomain,
        )
        db.add(cart)
        db.flush()
    elif (
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
    return db.scalar(
        select(Cart)
        .options(selectinload(Cart.items))
        .where(Cart.user_id == user_id)
    )


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
    cart = get_or_create_cart(
        db,
        user_id=user_id,
        restaurant_name=restaurant_name,
        subdomain=subdomain,
    )

    existing = next(
        (
            item
            for item in cart.items
            if item.item_key == item_key
        ),
        None,
    )

    if existing is None:
        existing = CartItem(
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
        db.add(existing)
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
    cart = get_cart(db, user_id=user_id)

    if cart is None:
        raise LookupError("Cart not found.")

    item = next(
        (
            item
            for item in cart.items
            if item.item_key == item_key
        ),
        None,
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
    cart = get_cart(db, user_id=user_id)

    if cart is None:
        raise LookupError("Cart not found.")

    item = next(
        (
            item
            for item in cart.items
            if item.item_key == item_key
        ),
        None,
    )

    if item is None:
        raise LookupError("Cart item not found.")

    db.delete(item)
    db.commit()

    return get_cart(db, user_id=user_id)


def clear_cart(
    db: Session,
    *,
    user_id: int,
) -> Cart | None:
    cart = get_cart(db, user_id=user_id)

    if cart is None:
        return None

    for item in list(cart.items):
        db.delete(item)

    db.commit()

    return get_cart(db, user_id=user_id)


def cart_total(cart: Cart | None) -> Decimal:
    if cart is None:
        return Decimal("0.00")

    return sum(
        (
            Decimal(str(item.unit_price)) * item.quantity
            for item in cart.items
        ),
        Decimal("0.00"),
    )
