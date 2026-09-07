"""Direct verification of LangGraph cart persistence."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.agents.state import (
    Cart,
    CartItem,
    CartItemUnit,
    ItemVariation,
)
from src.db.database import SessionLocal
from src.db.models import Cart as PersistentCart
from src.services.langgraph_cart import (
    load_langgraph_cart,
    persist_langgraph_cart,
)

from tests.test_authenticated_cart import signup_and_login


def _persistent_cart_snapshot(user_id: int) -> dict | None:
    """Read the persistent cart while its SQLAlchemy session is active."""

    with SessionLocal() as db:
        persistent = db.scalar(
            select(PersistentCart)
            .options(selectinload(PersistentCart.items))
            .where(PersistentCart.user_id == user_id)
        )

        if persistent is None:
            return None

        return {
            "restaurant_name": persistent.restaurant_name,
            "subdomain": persistent.subdomain,
            "items": [
                {
                    "item_id": item.item_id,
                    "title": item.title,
                    "item_key": item.item_key,
                    "quantity": item.quantity,
                    "unit_price": item.unit_price,
                    "variation_id": item.variation_id,
                    "variation_name": item.variation_name,
                    "variation_price": item.variation_price,
                }
                for item in persistent.items
            ],
        }


def _sample_cart(quantity: int = 2) -> Cart:
    return Cart(
        items=[
            CartItem(
                item_id="item-001",
                title="Chicken Biryani",
                units=[
                    CartItemUnit(
                        key="item-001|large",
                        quantity=quantity,
                        base_price=280.0,
                        variation=ItemVariation(
                            id="large",
                            name="Large",
                            price="280",
                        ),
                    )
                ],
            )
        ]
    )


def test_langgraph_add_state_persists_to_authenticated_cart():
    user_id, _ = signup_and_login()

    cart = _sample_cart(quantity=2)

    with SessionLocal() as db:
        persist_langgraph_cart(
            db,
            user_id=user_id,
            restaurant_name="Test Restaurant",
            subdomain="test",
            cart=cart,
        )

    persistent = _persistent_cart_snapshot(user_id)

    assert persistent is not None
    assert persistent["restaurant_name"] == "Test Restaurant"
    assert persistent["subdomain"] == "test"
    assert len(persistent["items"]) == 1

    item = persistent["items"][0]

    assert item["item_id"] == "item-001"
    assert item["title"] == "Chicken Biryani"
    assert item["item_key"] == "item-001|large"
    assert item["quantity"] == 2
    assert item["unit_price"] == Decimal("280.00")
    assert item["variation_id"] == "large"
    assert item["variation_name"] == "Large"
    assert item["variation_price"] == Decimal("280.00")


def test_langgraph_remove_state_persists_reduced_quantity():
    user_id, _ = signup_and_login()

    with SessionLocal() as db:
        persist_langgraph_cart(
            db,
            user_id=user_id,
            restaurant_name="Test Restaurant",
            subdomain="test",
            cart=_sample_cart(quantity=3),
        )

    reduced_cart = _sample_cart(quantity=1)

    with SessionLocal() as db:
        persist_langgraph_cart(
            db,
            user_id=user_id,
            restaurant_name="Test Restaurant",
            subdomain="test",
            cart=reduced_cart,
        )

    persistent = _persistent_cart_snapshot(user_id)

    assert persistent is not None
    assert len(persistent["items"]) == 1
    assert persistent["items"][0]["quantity"] == 1
    assert persistent["items"][0]["item_key"] == "item-001|large"


def test_langgraph_clear_state_clears_authenticated_cart():
    user_id, _ = signup_and_login()

    with SessionLocal() as db:
        persist_langgraph_cart(
            db,
            user_id=user_id,
            restaurant_name="Test Restaurant",
            subdomain="test",
            cart=_sample_cart(),
        )

    with SessionLocal() as db:
        persist_langgraph_cart(
            db,
            user_id=user_id,
            restaurant_name="Test Restaurant",
            subdomain="test",
            cart=Cart(items=[]),
        )

    persistent = _persistent_cart_snapshot(user_id)

    assert persistent is not None
    assert persistent["items"] == []


def test_langgraph_hydration_reconstructs_persistent_cart():
    user_id, _ = signup_and_login()

    original = _sample_cart(quantity=4)

    with SessionLocal() as db:
        persist_langgraph_cart(
            db,
            user_id=user_id,
            restaurant_name="Test Restaurant",
            subdomain="test",
            cart=original,
        )

    with SessionLocal() as db:
        hydrated = load_langgraph_cart(
            db,
            user_id=user_id,
            restaurant_name="Test Restaurant",
            subdomain="test",
        )

    assert len(hydrated.items) == 1

    item = hydrated.items[0]

    assert item.item_id == "item-001"
    assert item.title == "Chicken Biryani"
    assert len(item.units) == 1

    unit = item.units[0]

    assert unit.key == "item-001|large"
    assert unit.quantity == 4
    assert unit.base_price == 280.0
    assert unit.variation is not None
    assert unit.variation.id == "large"
    assert unit.variation.name == "Large"
    assert unit.variation.price == "280.00"


def test_langgraph_cart_rejects_restaurant_switch_with_existing_items():
    user_id, _ = signup_and_login()

    with SessionLocal() as db:
        persist_langgraph_cart(
            db,
            user_id=user_id,
            restaurant_name="Restaurant A",
            subdomain="restaurant-a",
            cart=_sample_cart(),
        )

    with SessionLocal() as db:
        try:
            load_langgraph_cart(
                db,
                user_id=user_id,
                restaurant_name="Restaurant B",
                subdomain="restaurant-b",
            )
        except ValueError as exc:
            assert "another restaurant" in str(exc)
        else:
            raise AssertionError(
                "Restaurant switching should be rejected while the cart has items."
            )
