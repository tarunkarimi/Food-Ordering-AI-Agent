"""Database repository for persistent shopping-cart data."""

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src.db.models import Cart, CartItem


def get_cart(
    db: Session,
    *,
    user_id: int,
) -> Cart | None:
    """Load a user's cart and its items."""
    return db.scalar(
        select(Cart)
        .options(selectinload(Cart.items))
        .where(Cart.user_id == user_id)
    )


def create_cart(
    db: Session,
    *,
    user_id: int,
    restaurant_name: str,
    subdomain: str,
) -> Cart:
    """Create and flush a new persistent cart."""
    cart = Cart(
        user_id=user_id,
        restaurant_name=restaurant_name,
        subdomain=subdomain,
    )
    db.add(cart)
    db.flush()
    return cart


def get_cart_item(
    cart: Cart,
    *,
    item_key: str,
) -> CartItem | None:
    """Find a cart item by its stable item key."""
    return next(
        (
            item
            for item in cart.items
            if item.item_key == item_key
        ),
        None,
    )


def add_cart_item(
    db: Session,
    *,
    cart: Cart,
    item_key: str,
    item_id: str,
    title: str,
    quantity: int,
    unit_price: float,
    variation_id: str | None,
    variation_name: str | None,
    variation_price: float | None,
) -> CartItem:
    """Add a new item to a cart."""
    item = CartItem(
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
    db.add(item)
    return item


def delete_cart_item(
    db: Session,
    *,
    item: CartItem,
) -> None:
    """Delete one cart item."""
    db.delete(item)


def delete_all_cart_items(
    db: Session,
    *,
    cart: Cart,
) -> None:
    """Delete all items currently belonging to a cart."""
    for item in list(cart.items):
        db.delete(item)
