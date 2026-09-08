import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.db.database import SessionLocal
from src.db.models import OrderHistory
from src.services.reorder import get_reorder_items
from tests.test_authenticated_cart import signup_and_login


def _create_order(
    *,
    user_id: int,
    order_id: str,
    items: list[dict],
    status: str = "confirmed",
):
    with SessionLocal() as db:
        order = OrderHistory(
            user_id=user_id,
            order_id=order_id,
            restaurant_name="Test Restaurant",
            subdomain="test",
            status=status,
            subtotal=220.0,
            total_items=sum(item["quantity"] for item in items),
            items_json=json.dumps(items),
        )
        db.add(order)
        db.commit()
        db.refresh(order)
        return order.id


def test_get_reorder_items_returns_historical_snapshot():
    user_id, _ = signup_and_login()
    order_id = f"REORDER-SERVICE-{uuid4()}"

    items = [
        {
            "item_id": "item-001",
            "title": "Chicken Biryani",
            "quantity": 2,
            "base_price": 280.0,
            "variation": {
                "id": "large",
                "name": "Large",
                "price": 280.0,
            },
        }
    ]

    _create_order(
        user_id=user_id,
        order_id=order_id,
        items=items,
    )

    with SessionLocal() as db:
        result = get_reorder_items(
            db,
            user_id=user_id,
            order_id=order_id,
        )

    assert result["order_id"] == order_id
    assert result["restaurant_name"] == "Test Restaurant"
    assert result["subdomain"] == "test"
    assert result["status"] == "confirmed"
    assert result["items"] == items


def test_get_reorder_items_blocks_another_user():
    user_a_id, _ = signup_and_login()
    user_b_id, _ = signup_and_login()

    order_id = f"REORDER-OWNER-{uuid4()}"

    _create_order(
        user_id=user_a_id,
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

    with SessionLocal() as db:
        with pytest.raises(LookupError, match="Order not found"):
            get_reorder_items(
                db,
                user_id=user_b_id,
                order_id=order_id,
            )


def test_get_reorder_items_rejects_missing_order():
    _, _ = signup_and_login()

    with SessionLocal() as db:
        with pytest.raises(LookupError, match="Order not found"):
            get_reorder_items(
                db,
                user_id=999999999,
                order_id=f"REORDER-MISSING-{uuid4()}",
            )


def test_get_reorder_items_rejects_empty_snapshot():
    user_id, _ = signup_and_login()
    order_id = f"REORDER-EMPTY-{uuid4()}"

    _create_order(
        user_id=user_id,
        order_id=order_id,
        items=[],
    )

    with SessionLocal() as db:
        with pytest.raises(
            ValueError,
            match="no reorderable items",
        ):
            get_reorder_items(
                db,
                user_id=user_id,
                order_id=order_id,
            )


def test_get_reorder_items_rejects_invalid_snapshot():
    user_id, _ = signup_and_login()
    order_id = f"REORDER-INVALID-{uuid4()}"

    with SessionLocal() as db:
        order = OrderHistory(
            user_id=user_id,
            order_id=order_id,
            restaurant_name="Test Restaurant",
            subdomain="test",
            status="confirmed",
            subtotal=220.0,
            total_items=1,
            items_json="{invalid-json",
        )
        db.add(order)
        db.commit()

    with SessionLocal() as db:
        with pytest.raises(
            ValueError,
            match="invalid item data",
        ):
            get_reorder_items(
                db,
                user_id=user_id,
                order_id=order_id,
            )
