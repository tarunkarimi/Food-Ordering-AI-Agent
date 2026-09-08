from uuid import uuid4
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.db.database import SessionLocal
from src.db.models.order_history import OrderHistory
from src.main import app
from tests.test_authenticated_cart import signup_and_login


client = TestClient(app)


def fake_menu(*args, **kwargs):
    return (
        [
            {
                "id": "item-001",
                "title": "Chicken Biryani",
                "description": "Test biryani",
                "base_price": 220.0,
                "variations": [
                    {"id": "regular", "name": "Regular", "price": 220.0},
                    {"id": "large", "name": "Large", "price": 280.0},
                ],
            }
        ],
        None,
    )


@patch("src.api.routes.cart._fetch_menu_items", side_effect=fake_menu)
@patch("src.api.routes.cart.requests.post")
def test_successful_checkout_clears_persistent_cart(
    mock_post,
    mock_menu,
):
    user_id, token = signup_and_login()
    order_id = f"order-test-001-{uuid4()}"

    add_response = client.post(
        "/api/cart/items",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "restaurant_name": "Test Restaurant",
            "subdomain": "test",
            "item_id": "item-001",
            "title": "Chicken Biryani",
            "quantity": 2,
            "variation_id": "large",
        },
    )

    assert add_response.status_code == 200

    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "order_id": order_id,
        "status": "confirmed",
        "subtotal": 560.0,
    }

    response = client.post(
        "/api/cart/checkout",
        headers={"Authorization": f"Bearer {token}"},
        json={"confirm": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["order_id"] == order_id
    assert body["status"] == "confirmed"

    cart_response = client.get(
        "/api/cart",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert cart_response.status_code == 200
    assert cart_response.json()["items"] == []

    with SessionLocal() as db:
        history = (
            db.query(OrderHistory)
            .filter(
                OrderHistory.user_id == user_id,
                OrderHistory.order_id == order_id,
            )
            .one()
        )

        assert history.status == "confirmed"
        assert history.total_items == 2
        assert float(history.subtotal) == 560.0


@patch("src.api.routes.cart._fetch_menu_items", side_effect=fake_menu)
@patch("src.api.routes.cart.requests.post")
def test_failed_checkout_preserves_persistent_cart(
    mock_post,
    mock_menu,
):
    _, token = signup_and_login()

    add_response = client.post(
        "/api/cart/items",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "restaurant_name": "Test Restaurant",
            "subdomain": "test",
            "item_id": "item-001",
            "title": "Chicken Biryani",
            "quantity": 1,
            "variation_id": "regular",
        },
    )

    assert add_response.status_code == 200

    mock_post.return_value.status_code = 503
    mock_post.return_value.json.return_value = {
        "detail": "Ordering service unavailable",
    }

    response = client.post(
        "/api/cart/checkout",
        headers={"Authorization": f"Bearer {token}"},
        json={"confirm": True},
    )

    assert response.status_code == 502

    cart_response = client.get(
        "/api/cart",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert cart_response.status_code == 200
    assert len(cart_response.json()["items"]) == 1


def test_checkout_requires_authentication():
    response = client.post(
        "/api/cart/checkout",
        json={"confirm": True},
    )

    assert response.status_code == 401


@patch("src.api.routes.cart._fetch_menu_items", side_effect=fake_menu)
def test_checkout_rejects_invalid_confirmation(mock_menu):
    _, token = signup_and_login()

    response = client.post(
        "/api/cart/checkout",
        headers={"Authorization": f"Bearer {token}"},
        json={"confirm": False},
    )

    assert response.status_code == 400


@patch("src.api.routes.cart._fetch_menu_items")
@patch("src.api.routes.cart.requests.post")
def test_checkout_revalidates_current_menu_price(
    mock_post,
    mock_menu,
):
    _, token = signup_and_login()
    order_id = f"order-test-002-{uuid4()}"

    initial_menu = [
        {
            "id": "item-001",
            "title": "Chicken Biryani",
            "description": "Test biryani",
            "base_price": 220.0,
            "variations": [
                {"id": "regular", "name": "Regular", "price": 220.0},
                {"id": "large", "name": "Large", "price": 280.0},
            ],
        }
    ]

    current_menu = [
        {
            "id": "item-001",
            "title": "Chicken Biryani",
            "description": "Test biryani",
            "base_price": 220.0,
            "variations": [
                {"id": "regular", "name": "Regular", "price": 250.0},
                {"id": "large", "name": "Large", "price": 300.0},
            ],
        }
    ]

    mock_menu.side_effect = [
        (initial_menu, None),
        (current_menu, None),
    ]

    add_response = client.post(
        "/api/cart/items",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "restaurant_name": "Test Restaurant",
            "subdomain": "test",
            "item_id": "item-001",
            "title": "Chicken Biryani",
            "quantity": 1,
            "variation_id": "regular",
        },
    )

    assert add_response.status_code == 200

    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "order_id": order_id,
        "status": "confirmed",
        "subtotal": 220.0,
    }

    response = client.post(
        "/api/cart/checkout",
        headers={"Authorization": f"Bearer {token}"},
        json={"confirm": True},
    )

    assert response.status_code == 409
    assert "price" in response.json()["detail"].lower()



