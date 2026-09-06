"""Authenticated persistent-cart API tests."""

from uuid import uuid4
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select

from src.db.database import SessionLocal
from src.db.models import Cart, User
from src.main import app


client = TestClient(app)


MENU_ITEMS = [
    {
        "id": "item-001",
        "title": "Chicken Biryani",
        "base_price": 220.0,
        "variations": [
            {"id": "regular", "name": "Regular", "price": 220.0},
            {"id": "large", "name": "Large", "price": 280.0},
        ],
    },
    {
        "id": "item-002",
        "title": "Masala Dosa",
        "base_price": 100.0,
        "variations": [],
    },
]


def unique_email() -> str:
    return f"cart-{uuid4().hex}@example.com"


def signup_and_login() -> tuple[int, str]:
    email = unique_email()
    password = "StrongPassword123!"

    signup = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": password,
        },
    )

    assert signup.status_code == 201

    user_id = signup.json()["id"]

    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        user.email_verified = True
        db.commit()

    login = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )

    assert login.status_code == 200

    return user_id, login.json()["access_token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def cart_item_payload(
    *,
    item_id: str = "item-001",
    title: str = "Chicken Biryani",
    quantity: int = 1,
    variation_id: str | None = "regular",
) -> dict:
    return {
        "restaurant_name": "Test Restaurant",
        "subdomain": "test",
        "item_id": item_id,
        "title": title,
        "quantity": quantity,
        "variation_id": variation_id,
    }


def fake_menu(*args, **kwargs):
    return MENU_ITEMS, None


def test_cart_requires_authentication():
    response = client.get("/api/cart")

    assert response.status_code == 401


@patch("src.api.routes.cart._fetch_menu_items", side_effect=fake_menu)
def test_authenticated_cart_starts_empty(mock_menu):
    _, token = signup_and_login()

    response = client.get(
        "/api/cart",
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["total"] == 0.0


@patch("src.api.routes.cart._fetch_menu_items", side_effect=fake_menu)
def test_add_cart_persists_and_uses_authoritative_variation_price(mock_menu):
    user_id, token = signup_and_login()

    payload = cart_item_payload(quantity=2, variation_id="large")

    response = client.post(
        "/api/cart/items",
        json=payload,
        headers=auth_headers(token),
    )

    assert response.status_code == 200

    body = response.json()

    assert body["restaurant_name"] == "Test Restaurant"
    assert body["subdomain"] == "test"
    assert body["items"][0]["item_key"] == "item-001|large"
    assert body["items"][0]["quantity"] == 2
    assert body["items"][0]["unit_price"] == 280.0
    assert body["items"][0]["variation"]["id"] == "large"
    assert body["items"][0]["variation"]["price"] == 280.0
    assert body["total"] == 560.0

    with SessionLocal() as db:
        cart = db.scalar(
            select(Cart).where(Cart.user_id == user_id)
        )

        assert cart is not None
        assert len(cart.items) == 1
        assert cart.items[0].quantity == 2
        assert float(cart.items[0].unit_price) == 280.0


@patch("src.api.routes.cart._fetch_menu_items", side_effect=fake_menu)
def test_same_item_and_variation_merges_quantity(mock_menu):
    _, token = signup_and_login()
    headers = auth_headers(token)

    first = client.post(
        "/api/cart/items",
        json=cart_item_payload(quantity=2, variation_id="regular"),
        headers=headers,
    )

    second = client.post(
        "/api/cart/items",
        json=cart_item_payload(quantity=3, variation_id="regular"),
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200

    body = second.json()

    assert len(body["items"]) == 1
    assert body["items"][0]["quantity"] == 5
    assert body["items"][0]["unit_price"] == 220.0
    assert body["total"] == 1100.0


@patch("src.api.routes.cart._fetch_menu_items", side_effect=fake_menu)
def test_different_variations_remain_separate(mock_menu):
    _, token = signup_and_login()
    headers = auth_headers(token)

    regular = client.post(
        "/api/cart/items",
        json=cart_item_payload(quantity=1, variation_id="regular"),
        headers=headers,
    )

    large = client.post(
        "/api/cart/items",
        json=cart_item_payload(quantity=1, variation_id="large"),
        headers=headers,
    )

    assert regular.status_code == 200
    assert large.status_code == 200

    body = large.json()

    assert len(body["items"]) == 2
    assert {item["item_key"] for item in body["items"]} == {
        "item-001|regular",
        "item-001|large",
    }
    assert body["total"] == 500.0


@patch("src.api.routes.cart._fetch_menu_items", side_effect=fake_menu)
def test_cart_survives_fresh_request(mock_menu):
    _, token = signup_and_login()
    headers = auth_headers(token)

    add = client.post(
        "/api/cart/items",
        json=cart_item_payload(quantity=2, variation_id="regular"),
        headers=headers,
    )

    assert add.status_code == 200

    fresh_request = client.get(
        "/api/cart",
        headers=headers,
    )

    assert fresh_request.status_code == 200
    assert fresh_request.json()["items"][0]["quantity"] == 2
    assert fresh_request.json()["total"] == 440.0


@patch("src.api.routes.cart._fetch_menu_items", side_effect=fake_menu)
def test_update_remove_and_clear_cart(mock_menu):
    _, token = signup_and_login()
    headers = auth_headers(token)

    add = client.post(
        "/api/cart/items",
        json=cart_item_payload(quantity=2, variation_id="regular"),
        headers=headers,
    )

    assert add.status_code == 200

    update = client.patch(
        "/api/cart/items/item-001|regular",
        json=cart_item_payload(quantity=4, variation_id="regular"),
        headers=headers,
    )

    assert update.status_code == 200
    assert update.json()["items"][0]["quantity"] == 4

    remove = client.delete(
        "/api/cart/items/item-001|regular",
        headers=headers,
    )

    assert remove.status_code == 200
    assert remove.json()["items"] == []

    add_again = client.post(
        "/api/cart/items",
        json=cart_item_payload(quantity=1, variation_id="regular"),
        headers=headers,
    )

    assert add_again.status_code == 200

    clear = client.delete(
        "/api/cart",
        headers=headers,
    )

    assert clear.status_code == 200
    assert clear.json()["items"] == []
    assert clear.json()["total"] == 0.0


@patch("src.api.routes.cart._fetch_menu_items", side_effect=fake_menu)
def test_user_cannot_access_another_users_cart(mock_menu):
    user_a, token_a = signup_and_login()
    user_b, token_b = signup_and_login()

    add = client.post(
        "/api/cart/items",
        json=cart_item_payload(quantity=2, variation_id="regular"),
        headers=auth_headers(token_a),
    )

    assert add.status_code == 200

    cart_a = client.get(
        "/api/cart",
        headers=auth_headers(token_a),
    )

    cart_b = client.get(
        "/api/cart",
        headers=auth_headers(token_b),
    )

    assert cart_a.status_code == 200
    assert cart_b.status_code == 200

    assert len(cart_a.json()["items"]) == 1
    assert cart_b.json()["items"] == []

    with SessionLocal() as db:
        cart = db.scalar(
            select(Cart).where(Cart.user_id == user_a)
        )

        assert cart is not None
        assert cart.user_id == user_a
        assert cart.user_id != user_b


@patch("src.api.routes.cart._fetch_menu_items", side_effect=fake_menu)
def test_invalid_item_is_rejected(mock_menu):
    _, token = signup_and_login()

    response = client.post(
        "/api/cart/items",
        json=cart_item_payload(
            item_id="item-does-not-exist",
            title="Unknown",
            quantity=1,
            variation_id=None,
        ),
        headers=auth_headers(token),
    )

    assert response.status_code == 400
    assert "not available" in response.json()["detail"]


@patch("src.api.routes.cart._fetch_menu_items", side_effect=fake_menu)
def test_invalid_variation_is_rejected(mock_menu):
    _, token = signup_and_login()

    response = client.post(
        "/api/cart/items",
        json=cart_item_payload(
            quantity=1,
            variation_id="not-a-real-variation",
        ),
        headers=auth_headers(token),
    )

    assert response.status_code == 400
    assert "variation" in response.json()["detail"].lower()


@patch("src.api.routes.cart._fetch_menu_items", side_effect=fake_menu)
def test_zero_quantity_is_rejected(mock_menu):
    _, token = signup_and_login()

    response = client.post(
        "/api/cart/items",
        json=cart_item_payload(
            quantity=0,
            variation_id="regular",
        ),
        headers=auth_headers(token),
    )

    assert response.status_code == 422


@patch("src.api.routes.cart._fetch_menu_items", side_effect=fake_menu)
def test_switching_restaurant_with_nonempty_cart_is_rejected(mock_menu):
    _, token = signup_and_login()
    headers = auth_headers(token)

    first = client.post(
        "/api/cart/items",
        json=cart_item_payload(quantity=1, variation_id="regular"),
        headers=headers,
    )

    assert first.status_code == 200

    second_payload = cart_item_payload(quantity=1, variation_id="regular")
    second_payload["restaurant_name"] = "Another Restaurant"
    second_payload["subdomain"] = "another"

    second = client.post(
        "/api/cart/items",
        json=second_payload,
        headers=headers,
    )

    assert second.status_code == 409
    assert "another restaurant" in second.json()["detail"].lower()
