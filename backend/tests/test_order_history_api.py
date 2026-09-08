"""Focused API tests for authenticated persistent order history."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from src.db.database import SessionLocal
from src.db.models import OrderHistory
from src.main import app

from tests.test_authenticated_cart import (
    auth_headers,
    signup_and_login,
)


client = TestClient(app)


def _order_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _create_order(
    *,
    user_id: int,
    order_id: str,
    created_at: datetime,
    title: str,
    subtotal: float,
):
    with SessionLocal() as db:
        order = OrderHistory(
            user_id=user_id,
            order_id=order_id,
            restaurant_name="Test Restaurant",
            subdomain="test",
            status="confirmed",
            subtotal=subtotal,
            total_items=1,
            items_json=(
                '[{"item_id":"item-001",'
                f'"title":"{title}",'
                '"quantity":1,'
                f'"base_price":{subtotal},'
                '"variation":null}]'
            ),
            created_at=created_at,
            updated_at=created_at,
        )

        db.add(order)
        db.commit()


def test_order_history_requires_authentication():
    response = client.get("/api/orders")

    assert response.status_code == 401


def test_order_history_list_returns_only_authenticated_users_orders():
    user_a_id, token_a = signup_and_login()
    user_b_id, _ = signup_and_login()

    now = datetime.now(timezone.utc)

    order_a = _order_id("HISTORY-A")
    order_b = _order_id("HISTORY-B")

    _create_order(
        user_id=user_a_id,
        order_id=order_a,
        created_at=now,
        title="Chicken Biryani",
        subtotal=220.0,
    )

    _create_order(
        user_id=user_b_id,
        order_id=order_b,
        created_at=now,
        title="Mutton Biryani",
        subtotal=300.0,
    )

    response = client.get(
        "/api/orders",
        headers=auth_headers(token_a),
    )

    assert response.status_code == 200

    data = response.json()

    assert data["limit"] == 50
    assert data["offset"] == 0

    orders = data["orders"]

    assert any(
        order["order_id"] == order_a
        for order in orders
    )

    assert not any(
        order["order_id"] == order_b
        for order in orders
    )

    order = next(
        order
        for order in orders
        if order["order_id"] == order_a
    )

    assert order["restaurant_name"] == "Test Restaurant"
    assert order["subdomain"] == "test"
    assert order["status"] == "confirmed"
    assert order["subtotal"] == 220.0
    assert order["total_items"] == 1
    assert order["items"][0]["title"] == "Chicken Biryani"


def test_order_history_detail_allows_owner_and_blocks_other_users():
    user_a_id, token_a = signup_and_login()
    _, token_b = signup_and_login()

    order_id = _order_id("HISTORY-OWNER")

    _create_order(
        user_id=user_a_id,
        order_id=order_id,
        created_at=datetime.now(timezone.utc),
        title="Chicken Biryani",
        subtotal=220.0,
    )

    own_response = client.get(
        f"/api/orders/{order_id}",
        headers=auth_headers(token_a),
    )

    assert own_response.status_code == 200
    assert own_response.json()["order_id"] == order_id

    other_response = client.get(
        f"/api/orders/{order_id}",
        headers=auth_headers(token_b),
    )

    assert other_response.status_code == 404


def test_order_history_detail_returns_404_for_unknown_order():
    _, token = signup_and_login()

    response = client.get(
        f"/api/orders/{_order_id('ORDER-DOES-NOT-EXIST')}",
        headers=auth_headers(token),
    )

    assert response.status_code == 404


def test_order_history_pagination():
    user_id, token = signup_and_login()

    base_time = datetime.now(timezone.utc)

    order_ids = []

    for index in range(3):
        order_id = _order_id(f"HISTORY-PAGE-{index}")
        order_ids.append(order_id)

        _create_order(
            user_id=user_id,
            order_id=order_id,
            created_at=base_time + timedelta(seconds=index),
            title=f"Item {index}",
            subtotal=100.0 + index,
        )

    response = client.get(
        "/api/orders?limit=2&offset=1",
        headers=auth_headers(token),
    )

    assert response.status_code == 200

    data = response.json()

    assert data["limit"] == 2
    assert data["offset"] == 1
    assert len(data["orders"]) == 2

    # Newest first: index 2, index 1, index 0.
    assert data["orders"][0]["order_id"] == order_ids[1]
    assert data["orders"][1]["order_id"] == order_ids[0]
