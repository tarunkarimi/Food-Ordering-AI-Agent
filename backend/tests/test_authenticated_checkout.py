from uuid import uuid4
from unittest.mock import patch
import sys
import requests
import pytest
from sqlalchemy import delete

from fastapi.testclient import TestClient

from src.db.database import SessionLocal
from src.db.models import User
from src.db.models.order_operation import OrderOperation
from src.db.models.order_history import OrderHistory
from src.main import app
from tests.test_authenticated_cart import signup_and_login


client = TestClient(app)


@pytest.fixture(autouse=True)
def cleanup_synthetic_checkout_users(monkeypatch):
    original_signup = signup_and_login
    created_user_ids = []

    def tracked_signup():
        user_id, token = original_signup()
        created_user_ids.append(user_id)
        return user_id, token

    monkeypatch.setattr(sys.modules[__name__], "signup_and_login", tracked_signup)
    yield
    if created_user_ids:
        with SessionLocal() as db:
            db.execute(delete(User).where(User.id.in_(created_user_ids)))
            db.commit()


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


def checkout_headers(token: str, key: str | None = None):
    return {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": key or f"checkout-test-{uuid4().hex}",
    }


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
        headers=checkout_headers(token),
        json={"confirm": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["order_id"] == order_id
    assert body["status"] == "confirmed"
    assert mock_post.call_args.kwargs["headers"]["Idempotency-Key"]
    assert mock_post.call_args.kwargs["json"]["user_id"] == str(user_id)

    cart_response = client.get(
        "/api/cart",
        headers=checkout_headers(token),
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
        headers=checkout_headers(token),
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
        headers=checkout_headers(token),
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
        headers=checkout_headers(token),
        json={"confirm": True},
    )

    assert response.status_code == 409
    assert "price" in response.json()["detail"].lower()


@patch("src.api.routes.cart._fetch_menu_items", side_effect=fake_menu)
@patch("src.api.routes.cart.requests.post")
def test_checkout_retry_after_lost_response_reuses_key_and_order(mock_post, _mock_menu):
    user_id, token = signup_and_login()
    client.post(
        "/api/cart/items",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "restaurant_name": "Test Restaurant", "subdomain": "test",
            "item_id": "item-001", "title": "Chicken Biryani",
            "quantity": 1, "variation_id": "regular",
        },
    )
    key = f"checkout-lost-response-{uuid4().hex}"
    accepted = {"order_id": f"ORD-{uuid4().hex.upper()}", "status": "confirmed", "subtotal": 220.0}

    def accepted_then_timeout(*args, **kwargs):
        if mock_post.call_count == 1:
            raise requests.Timeout("synthetic response loss")
        return type("Response", (), {
            "status_code": 201,
            "json": lambda self: accepted,
            "raise_for_status": lambda self: None,
        })()

    mock_post.side_effect = accepted_then_timeout
    headers = checkout_headers(token, key)
    first = client.post("/api/cart/checkout", headers=headers, json={"confirm": True})
    retry = client.post("/api/cart/checkout", headers=headers, json={"confirm": True})

    assert first.status_code == 503
    assert retry.status_code == 200
    assert retry.json()["order_id"] == accepted["order_id"]
    assert [call.kwargs["headers"]["Idempotency-Key"] for call in mock_post.call_args_list] == [key, key]
    with SessionLocal() as db:
        assert db.query(OrderHistory).filter(
            OrderHistory.user_id == user_id,
            OrderHistory.order_id == accepted["order_id"],
        ).count() == 1


@patch("src.api.routes.cart._fetch_menu_items", side_effect=fake_menu)
@patch("src.api.routes.cart.requests.post")
def test_malformed_upstream_response_stays_retryable_with_same_key(mock_post, _mock_menu):
    user_id, token = signup_and_login()
    client.post(
        "/api/cart/items",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "restaurant_name": "Test Restaurant", "subdomain": "test",
            "item_id": "item-001", "title": "Chicken Biryani",
            "quantity": 1, "variation_id": "regular",
        },
    )
    key = f"checkout-malformed-response-{uuid4().hex}"
    accepted = {
        "order_id": f"ORD-{uuid4().hex.upper()}",
        "status": "confirmed",
        "subtotal": 220.0,
    }

    def response(body):
        return type("Response", (), {
            "status_code": 201,
            "json": lambda self: body,
            "raise_for_status": lambda self: None,
        })()

    mock_post.side_effect = [
        response({"order_id": accepted["order_id"], "status": "confirmed"}),
        response(accepted),
    ]
    headers = checkout_headers(token, key)

    first = client.post("/api/cart/checkout", headers=headers, json={"confirm": True})
    with SessionLocal() as db:
        operation = db.query(OrderOperation).filter(
            OrderOperation.user_id == user_id,
            OrderOperation.idempotency_key == key,
        ).one()
        assert operation.status == "pending"
        assert operation.upstream_order_id is None

    retry = client.post("/api/cart/checkout", headers=headers, json={"confirm": True})

    assert first.status_code == 502
    assert retry.status_code == 200
    assert retry.json()["order_id"] == accepted["order_id"]
    assert [call.kwargs["headers"]["Idempotency-Key"] for call in mock_post.call_args_list] == [key, key]


@patch("src.api.routes.cart._fetch_menu_items", side_effect=fake_menu)
@patch("src.api.routes.cart.requests.post")
def test_checkout_recovers_local_history_without_reposting_confirmed_order(mock_post, _mock_menu):
    _, token = signup_and_login()
    client.post(
        "/api/cart/items",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "restaurant_name": "Test Restaurant", "subdomain": "test",
            "item_id": "item-001", "title": "Chicken Biryani",
            "quantity": 1, "variation_id": "regular",
        },
    )
    key = f"checkout-history-recovery-{uuid4().hex}"
    accepted = {"order_id": f"ORD-{uuid4().hex.upper()}", "status": "confirmed", "subtotal": 220.0}
    mock_post.return_value.status_code = 201
    mock_post.return_value.json.return_value = accepted
    mock_post.return_value.raise_for_status.return_value = None

    from src.api.routes import cart as cart_route
    real_create_history = cart_route.create_order_history
    with patch.object(
        cart_route,
        "create_order_history",
        side_effect=[RuntimeError("synthetic local persistence failure"), real_create_history],
    ):
        headers = checkout_headers(token, key)
        first = client.post("/api/cart/checkout", headers=headers, json={"confirm": True})
        retry = client.post("/api/cart/checkout", headers=headers, json={"confirm": True})

    assert first.status_code == 503
    assert retry.status_code == 200
    assert mock_post.call_count == 1



