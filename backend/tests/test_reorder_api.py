"""Authenticated reorder API tests."""

import json
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from src.db.database import SessionLocal
from src.db.models import OrderHistory
from src.main import app

from tests.test_authenticated_cart import signup_and_login


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


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_history(
    *,
    user_id: int,
    order_id: str | None = None,
    items: list | None = None,
):
    with SessionLocal() as db:
        order = OrderHistory(
            user_id=user_id,
            order_id=order_id or f"REORDER-{uuid4().hex}",
            restaurant_name="Test Restaurant",
            subdomain="test",
            status="confirmed",
            subtotal=220.00,
            total_items=1,
            items_json=json.dumps(
                items
                if items is not None
                else [
                    {
                        "item_id": "item-001",
                        "title": "Chicken Biryani",
                        "quantity": 1,
                        "base_price": 220.0,
                        "variation": {
                            "id": "regular",
                            "name": "Regular",
                            "price": 220.0,
                        },
                    }
                ]
            ),
        )
        db.add(order)
        db.commit()
        db.refresh(order)
        return order.order_id


def fake_menu(*args, **kwargs):
    return MENU_ITEMS, None


@patch("src.services.reorder._fetch_menu_items", side_effect=fake_menu)
def test_reorder_returns_current_menu_item_and_price(mock_menu):
    user_id, token = signup_and_login()

    order_id = create_history(
        user_id=user_id,
        items=[
            {
                "item_id": "item-001",
                "title": "Chicken Biryani",
                "quantity": 2,
                "base_price": 180.0,
                "variation": {
                    "id": "regular",
                    "name": "Old Regular",
                    "price": 180.0,
                },
            }
        ],
    )

    response = client.post(
        f"/api/orders/{order_id}/reorder",
        headers=auth_headers(token),
    )

    assert response.status_code == 200

    data = response.json()

    assert data["success"] is True
    assert data["items"][0]["quantity"] == 2
    assert data["items"][0]["base_price"] == 220.0
    assert data["items"][0]["variation"]["id"] == "regular"
    assert data["items"][0]["variation"]["name"] == "Regular"
    assert data["items"][0]["variation"]["price"] == 220.0


@patch("src.services.reorder._fetch_menu_items", side_effect=fake_menu)
def test_reorder_supports_current_no_variation_item(mock_menu):
    user_id, token = signup_and_login()

    order_id = create_history(
        user_id=user_id,
        items=[
            {
                "item_id": "item-002",
                "title": "Masala Dosa",
                "quantity": 2,
                "base_price": 80.0,
                "variation": None,
            }
        ],
    )

    response = client.post(
        f"/api/orders/{order_id}/reorder",
        headers=auth_headers(token),
    )

    assert response.status_code == 200

    item = response.json()["items"][0]

    assert item["item_id"] == "item-002"
    assert item["quantity"] == 2
    assert item["base_price"] == 100.0
    assert item["variation"] is None


@patch("src.services.reorder._fetch_menu_items", return_value=([], None))
def test_reorder_rejects_removed_item(mock_menu):
    user_id, token = signup_and_login()

    order_id = create_history(user_id=user_id)

    response = client.post(
        f"/api/orders/{order_id}/reorder",
        headers=auth_headers(token),
    )

    assert response.status_code == 409
    assert "no longer available" in response.json()["detail"]


@patch(
    "src.services.reorder._fetch_menu_items",
    return_value=(
        [
            {
                "id": "item-001",
                "title": "Chicken Biryani",
                "base_price": 220.0,
                "variations": [
                    {
                        "id": "large",
                        "name": "Large",
                        "price": 280.0,
                    }
                ],
            }
        ],
        None,
    ),
)
def test_reorder_rejects_removed_variation(mock_menu):
    user_id, token = signup_and_login()

    order_id = create_history(user_id=user_id)

    response = client.post(
        f"/api/orders/{order_id}/reorder",
        headers=auth_headers(token),
    )

    assert response.status_code == 409
    assert "variation" in response.json()["detail"].lower()
    assert "no longer available" in response.json()["detail"]


@patch(
    "src.services.reorder._fetch_menu_items",
    return_value=([], "The menu service is unavailable. Please try again."),
)
def test_reorder_returns_503_when_menu_service_fails(mock_menu):
    user_id, token = signup_and_login()

    order_id = create_history(user_id=user_id)

    response = client.post(
        f"/api/orders/{order_id}/reorder",
        headers=auth_headers(token),
    )

    assert response.status_code == 503
    assert "menu service is unavailable" in response.json()["detail"].lower()


def test_reorder_requires_authentication():
    order_id = f"REORDER-{uuid4().hex}"

    response = client.post(
        f"/api/orders/{order_id}/reorder",
    )

    assert response.status_code == 401


def test_reorder_blocks_another_user():
    owner_id, _ = signup_and_login()
    _, other_token = signup_and_login()

    order_id = create_history(user_id=owner_id)

    response = client.post(
        f"/api/orders/{order_id}/reorder",
        headers=auth_headers(other_token),
    )

    assert response.status_code == 404


def test_reorder_missing_order_returns_404():
    _, token = signup_and_login()

    order_id = f"REORDER-{uuid4().hex}"

    response = client.post(
        f"/api/orders/{order_id}/reorder",
        headers=auth_headers(token),
    )

    assert response.status_code == 404


def test_reorder_rejects_empty_historical_items():
    user_id, token = signup_and_login()

    order_id = create_history(
        user_id=user_id,
        items=[],
    )

    response = client.post(
        f"/api/orders/{order_id}/reorder",
        headers=auth_headers(token),
    )

    assert response.status_code == 409
    assert "no reorderable items" in response.json()["detail"]


def test_reorder_rejects_invalid_historical_items():
    user_id, token = signup_and_login()

    order_id = create_history(
        user_id=user_id,
        items=["invalid-item"],
    )

    response = client.post(
        f"/api/orders/{order_id}/reorder",
        headers=auth_headers(token),
    )

    assert response.status_code == 409
    assert "invalid item data" in response.json()["detail"]
