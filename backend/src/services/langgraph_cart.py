"""Synchronize authenticated persistent carts with LangGraph cart state."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src.agents.state import Cart, CartItem, CartItemUnit, ItemVariation
from src.db.models import Cart as PersistentCart


def load_langgraph_cart(
    db: Session,
    *,
    user_id: int,
    restaurant_name: str,
    subdomain: str,
) -> Cart:
    """
    Load the authenticated user's persistent cart into LangGraph format.

    An empty persistent cart produces an empty LangGraph cart.

    A cart containing items for another restaurant is intentionally not
    silently reassigned. The caller must handle the restaurant mismatch.
    """

    persistent_cart = db.scalar(
        select(PersistentCart)
        .options(selectinload(PersistentCart.items))
        .where(PersistentCart.user_id == user_id)
    )

    if persistent_cart is None or not persistent_cart.items:
        return Cart(items=[])

    if (
        persistent_cart.restaurant_name != restaurant_name
        or persistent_cart.subdomain != subdomain
    ):
        raise ValueError(
            "Your existing cart belongs to another restaurant. "
            "Please clear that cart before starting an order here."
        )

    items_by_id: dict[str, CartItem] = {}

    for item in persistent_cart.items:
        variation = None

        if item.variation_id is not None:
            variation = ItemVariation(
                id=item.variation_id,
                name=item.variation_name or "",
                price=str(
                    item.variation_price
                    if item.variation_price is not None
                    else item.unit_price
                ),
            )

        unit = CartItemUnit(
            key=item.item_key,
            quantity=item.quantity,
            base_price=float(item.unit_price),
            variation=variation,
        )

        existing = items_by_id.get(item.item_id)

        if existing is None:
            items_by_id[item.item_id] = CartItem(
                item_id=item.item_id,
                title=item.title,
                units=[unit],
            )
        else:
            existing.units.append(unit)
            existing.title = item.title

    return Cart(items=list(items_by_id.values()))


def persist_langgraph_cart(
    db: Session,
    *,
    user_id: int,
    restaurant_name: str,
    subdomain: str,
    cart: Cart | None,
) -> None:
    """
    Persist the LangGraph cart as the authenticated user's cart.

    This operation replaces the persistent cart contents atomically
    within the current database transaction.
    """

    if cart is None:
        cart = Cart(items=[])

    persistent_cart = db.scalar(
        select(PersistentCart)
        .options(selectinload(PersistentCart.items))
        .where(PersistentCart.user_id == user_id)
    )

    if persistent_cart is None:
        persistent_cart = PersistentCart(
            user_id=user_id,
            restaurant_name=restaurant_name,
            subdomain=subdomain,
        )
        db.add(persistent_cart)
        db.flush()

    elif (
        persistent_cart.items
        and (
            persistent_cart.restaurant_name != restaurant_name
            or persistent_cart.subdomain != subdomain
        )
    ):
        raise ValueError(
            "Your existing cart belongs to another restaurant. "
            "Please clear that cart before switching restaurants."
        )

    persistent_cart.restaurant_name = restaurant_name
    persistent_cart.subdomain = subdomain

    for item in list(persistent_cart.items):
        db.delete(item)

    db.flush()

    for cart_item in cart.items:
        for unit in cart_item.units:
            variation_id = None
            variation_name = None
            variation_price = None

            if unit.variation is not None:
                variation_id = unit.variation.id
                variation_name = unit.variation.name

                try:
                    variation_price = Decimal(
                        str(unit.variation.price)
                    )
                except (TypeError, ValueError):
                    variation_price = Decimal(
                        str(unit.base_price)
                    )

            persistent_cart.items.append(
                __import__(
                    "src.db.models",
                    fromlist=["CartItem"],
                ).CartItem(
                    item_key=unit.key,
                    item_id=cart_item.item_id,
                    title=cart_item.title,
                    quantity=unit.quantity,
                    unit_price=Decimal(str(unit.base_price)),
                    variation_id=variation_id,
                    variation_name=variation_name,
                    variation_price=variation_price,
                )
            )

    db.commit()


def synchronize_langgraph_cart(
    db: Session,
    *,
    user_id: int,
    restaurant_name: str,
    subdomain: str,
    cart: Cart | None,
) -> Cart:
    """Persist the current LangGraph cart and return that cart."""

    if cart is None:
        cart = Cart(items=[])

    persist_langgraph_cart(
        db,
        user_id=user_id,
        restaurant_name=restaurant_name,
        subdomain=subdomain,
        cart=cart,
    )

    return cart
