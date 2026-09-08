"""Tests for authenticated reorder-to-cart behavior."""

import json
from uuid import uuid4

from fastapi.testclient import TestClient

from src.db.database import SessionLocal
from src.db.models import Cart, CartItem, OrderHistory
from src.main import app
from tests.test_authenticated_cart import signup_and_login


client = TestClient(app)


def unique_order_id(prefix="REORDER-CART"):
    return f"{prefix}-{uuid4().hex}"


def create_history(
    *,
    user_id: int,
    order_id: str,
    restaurant_name="Test Restaurant",
    subdomain="test",
    items=None,
):
    db = SessionLocal()

    try:
        items = items or []

        history = OrderHistory(
            user_id=user_id,
            order_id=order_id,
            restaurant_name=restaurant_name,
            subdomain=subdomain,
            status="confirmed",
            subtotal=220.00,
            total_items=sum(
                item["quantity"]
                for item in items
            ),
            items_json=json.dumps(items),
        )

        db.add(history)
        db.commit()
        db.refresh(history)

        return history
    finally:
        db.close()


def test_reorder_populates_persistent_cart_with_current_price(monkeypatch):
    user_id, token = signup_and_login()

    order_id = unique_order_id()

    create_history(
        user_id=user_id,
        order_id=order_id,
        items=[
            {
                "item_id": "item-001",
                "title": "Chicken Biryani",
                "quantity": 2,
                "base_price": 180.0,
                "variation": {
                    "id": "regular",
                    "name": "Regular",
                    "price": 180.0,
                },
            }
        ],
    )

    monkeypatch.setattr(
        "src.services.reorder._fetch_menu_items",
        lambda payload: (
            [
                {
                    "id": "item-001",
                    "title": "Chicken Biryani",
                    "base_price": 220.0,
                    "variations": [
                        {
                            "id": "regular",
                            "name": "Regular",
                            "price": "220",
                        }
                    ],
                }
            ],
            None,
        ),
    )

    response = client.post(
        f"/api/orders/{order_id}/reorder",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200

    data = response.json()

    assert data["success"] is True
    assert data["order_id"] == order_id
    assert len(data["cart"]["items"]) == 1

    item = data["cart"]["items"][0]

    assert item["item_id"] == "item-001"
    assert item["title"] == "Chicken Biryani"
    assert item["quantity"] == 2
    assert item["unit_price"] == 220.0
    assert item["variation"]["id"] == "regular"
    assert item["variation"]["price"] == 220.0

    db = SessionLocal()

    try:
        cart = db.query(Cart).filter(Cart.user_id == user_id).first()

        assert cart is not None
        assert len(cart.items) == 1
        assert cart.items[0].quantity == 2
        assert float(cart.items[0].unit_price) == 220.0
    finally:
        db.close()


def test_reorder_adds_quantity_to_existing_cart_item(monkeypatch):
    user_id, token = signup_and_login()

    order_id = unique_order_id()

    create_history(
        user_id=user_id,
        order_id=order_id,
        items=[
            {
                "item_id": "item-001",
                "title": "Chicken Biryani",
                "quantity": 2,
                "base_price": 220.0,
                "variation": None,
            }
        ],
    )

    monkeypatch.setattr(
        "src.services.reorder._fetch_menu_items",
        lambda payload: (
            [
                {
                    "id": "item-001",
                    "title": "Chicken Biryani",
                    "base_price": 220.0,
                    "variations": [],
                }
            ],
            None,
        ),
    )

    first = client.post(
        f"/api/orders/{order_id}/reorder",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert first.status_code == 200
    assert first.json()["cart"]["items"][0]["quantity"] == 2

    second = client.post(
        f"/api/orders/{order_id}/reorder",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert second.status_code == 200
    assert second.json()["cart"]["items"][0]["quantity"] == 4

    db = SessionLocal()

    try:
        cart = db.query(Cart).filter(Cart.user_id == user_id).first()

        assert cart is not None
        assert len(cart.items) == 1
        assert cart.items[0].quantity == 4
    finally:
        db.close()


def test_reorder_rejects_switching_from_nonempty_other_restaurant_cart(
    monkeypatch,
):
    user_id, token = signup_and_login()

    db = SessionLocal()

    try:
        cart = Cart(
            user_id=user_id,
            restaurant_name="Other Restaurant",
            subdomain="other",
        )

        db.add(cart)
        db.flush()

        db.add(
            CartItem(
                cart_id=cart.id,
                item_key="existing-item|no_variant",
                item_id="existing-item",
                title="Existing Item",
                quantity=1,
                unit_price=100.0,
                variation_id=None,
                variation_name=None,
                variation_price=None,
            )
        )

        order_id = unique_order_id()

        db.add(
            OrderHistory(
                user_id=user_id,
                order_id=order_id,
                restaurant_name="Test Restaurant",
                subdomain="test",
                status="confirmed",
                subtotal=220.0,
                total_items=1,
                items_json=json.dumps(
                    [
                        {
                            "item_id": "item-001",
                            "title": "Chicken Biryani",
                            "quantity": 1,
                            "base_price": 220.0,
                            "variation": None,
                        }
                    ]
                ),
            )
        )

        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(
        "src.services.reorder._fetch_menu_items",
        lambda payload: (
            [
                {
                    "id": "item-001",
                    "title": "Chicken Biryani",
                    "base_price": 220.0,
                    "variations": [],
                }
            ],
            None,
        ),
    )

    response = client.post(
        f"/api/orders/{order_id}/reorder",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 409
    assert "another restaurant" in response.json()["detail"].lower()

    db = SessionLocal()

    try:
        cart = db.query(Cart).filter(Cart.user_id == user_id).first()

        assert cart is not None
        assert cart.restaurant_name == "Other Restaurant"
        assert len(cart.items) == 1
        assert cart.items[0].item_id == "existing-item"
    finally:
        db.close()


def test_reorder_does_not_checkout(monkeypatch):
    user_id, token = signup_and_login()

    order_id = unique_order_id()

    create_history(
        user_id=user_id,
        order_id=order_id,
        items=[
            {
                "item_id": "item-001",
                "title": "Chicken Biryani",
                "quantity": 1,
                "base_price": 220.0,
                "variation": None,
            }
        ],
    )

    monkeypatch.setattr(
        "src.services.reorder._fetch_menu_items",
        lambda payload: (
            [
                {
                    "id": "item-001",
                    "title": "Chicken Biryani",
                    "base_price": 220.0,
                    "variations": [],
                }
            ],
            None,
        ),
    )

    response = client.post(
        f"/api/orders/{order_id}/reorder",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200

    data = response.json()

    assert data["cart"]["items"]
    assert data["cart"]["items"][0]["title"] == "Chicken Biryani"

    db = SessionLocal()

    try:
        history = (
            db.query(OrderHistory)
            .filter(OrderHistory.order_id == order_id)
            .first()
        )

        assert history is not None
        assert history.status == "confirmed"

        cart = db.query(Cart).filter(Cart.user_id == user_id).first()

        assert cart is not None
        assert len(cart.items) == 1
    finally:
        db.close()
