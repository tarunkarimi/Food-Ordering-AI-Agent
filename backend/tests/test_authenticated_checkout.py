"""Authenticated persistent-cart checkout tests."""

from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select

from src.db.database import SessionLocal
from src.db.models import Cart
from src.main import app

from tests.test_authenticated_cart import (
    auth_headers,
    cart_item_payload,
    fake_menu,
    signup_and_login,
)

client = TestClient(app)


def test_checkout_requires_confirmation():
    _, token = signup_and_login()

    response = client.post(
        "/api/cart/checkout",
        json={"confirm": False},
        headers=auth_headers(token),
    )

    assert response.status_code == 400
    assert "confirmation" in response.json()["detail"].lower()


@patch("src.api.routes.cart._fetch_menu_items", side_effect=fake_menu)
@patch("src.api.routes.cart.requests.post")
def test_successful_checkout_clears_persistent_cart(
    mock_post,
    mock_menu,
):
    user_id, token = signup_and_login()

    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "order_id": "order-test-001",
        "status": "confirmed",
        "subtotal": 560.0,
    }
    mock_post.return_value.raise_for_status.return_value = None

    headers = auth_headers(token)

    add = client.post(
        "/api/cart/items",
        json=cart_item_payload(
            quantity=2,
            variation_id="large",
        ),
        headers=headers,
    )

    assert add.status_code == 200
    assert add.json()["total"] == 560.0

    checkout = client.post(
        "/api/cart/checkout",
        json={"confirm": True},
        headers=headers,
    )

    assert checkout.status_code == 200

    body = checkout.json()

    assert body["success"] is True
    assert body["order_id"] == "order-test-001"
    assert body["status"] == "confirmed"
    assert body["subtotal"] == 560.0
    assert body["total_items"] == 2
    assert body["cart"]["items"] == []
    assert body["cart"]["total"] == 0.0

    mock_post.assert_called_once()

    payload = mock_post.call_args.kwargs["json"]

    assert payload["restaurant_name"] == "Test Restaurant"
    assert payload["subdomain"] == "test"
    assert payload["items"][0]["item_id"] == "item-001"
    assert payload["items"][0]["quantity"] == 2
    assert payload["items"][0]["base_price"] == 280.0
    assert payload["items"][0]["variation"]["id"] == "large"

    with SessionLocal() as db:
        cart = db.scalar(
            select(Cart).where(
                Cart.user_id == user_id
            )
        )

        assert cart is not None
        assert cart.items == []


@patch("src.api.routes.cart._fetch_menu_items", side_effect=fake_menu)
@patch("src.api.routes.cart.requests.post")
def test_failed_checkout_preserves_persistent_cart(
    mock_post,
    mock_menu,
):
    user_id, token = signup_and_login()

    mock_post.side_effect = RuntimeError(
        "unexpected test failure"
    )

    headers = auth_headers(token)

    add = client.post(
        "/api/cart/items",
        json=cart_item_payload(
            quantity=2,
            variation_id="regular",
        ),
        headers=headers,
    )

    assert add.status_code == 200

    checkout = client.post(
        "/api/cart/checkout",
        json={"confirm": True},
        headers=headers,
    )

    assert checkout.status_code == 503
    assert "cart was preserved" in checkout.json()["detail"].lower()

    with SessionLocal() as db:
        cart = db.scalar(
            select(Cart).where(
                Cart.user_id == user_id
            )
        )

        assert cart is not None
        assert len(cart.items) == 1
        assert cart.items[0].quantity == 2


@patch("src.api.routes.cart._fetch_menu_items", side_effect=fake_menu)
@patch("src.api.routes.cart.requests.post")
def test_checkout_revalidates_current_menu_price(
    mock_post,
    mock_menu,
):
    _, token = signup_and_login()

    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "order_id": "order-test-002",
        "status": "confirmed",
        "subtotal": 220.0,
    }
    mock_post.return_value.raise_for_status.return_value = None

    headers = auth_headers(token)

    add = client.post(
        "/api/cart/items",
        json=cart_item_payload(
            quantity=1,
            variation_id="regular",
        ),
        headers=headers,
    )

    assert add.status_code == 200

    checkout = client.post(
        "/api/cart/checkout",
        json={"confirm": True},
        headers=headers,
    )

    assert checkout.status_code == 200

    payload = mock_post.call_args.kwargs["json"]

    assert payload["items"][0]["base_price"] == 220.0


def test_checkout_requires_authentication():
    response = client.post(
        "/api/cart/checkout",
        json={"confirm": True},
    )

    assert response.status_code == 401
