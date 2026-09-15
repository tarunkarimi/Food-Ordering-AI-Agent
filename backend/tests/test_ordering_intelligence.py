"""Ordering intelligence tests."""

import json
from uuid import uuid4

from src.db.database import SessionLocal
from src.db.models import OrderHistory
from src.services.ordering_intelligence import (
    build_ai_ordering_context,
    build_ordering_intelligence,
    build_smart_reorder_suggestions,
)
from tests.test_authenticated_cart import signup_and_login


def _create_order(
    *,
    user_id: int,
    restaurant_name: str,
    items: list[dict],
):
    order_id = f"ORDER-INTEL-{uuid4().hex}"

    with SessionLocal() as db:
        order = OrderHistory(
            user_id=user_id,
            order_id=order_id,
            restaurant_name=restaurant_name,
            subdomain="test",
            status="confirmed",
            subtotal=220.0,
            total_items=sum(item["quantity"] for item in items),
            items_json=json.dumps(items),
        )
        db.add(order)
        db.commit()
        db.refresh(order)

    return order_id


def test_ordering_intelligence_frequency():
    user_id, _ = signup_and_login()

    _create_order(
        user_id=user_id,
        restaurant_name="Test Restaurant",
        items=[{"item_id": "item-001", "title": "Biryani", "quantity": 2}],
    )
    _create_order(
        user_id=user_id,
        restaurant_name="Test Restaurant",
        items=[{"item_id": "item-001", "title": "Biryani", "quantity": 1}],
    )

    with SessionLocal() as db:
        result = build_ordering_intelligence(db, user_id)

    assert result["orders_analyzed"] == 2
    assert result["usual_items"][0]["title"] == "Biryani"
    assert result["usual_items"][0]["order_count"] == 2
    assert result["usual_items"][0]["total_quantity"] == 3


def test_ordering_intelligence_restaurant_scope():
    user_id, _ = signup_and_login()

    _create_order(
        user_id=user_id,
        restaurant_name="Restaurant A",
        items=[{"item_id": "item-001", "title": "Pizza", "quantity": 1}],
    )
    _create_order(
        user_id=user_id,
        restaurant_name="Restaurant B",
        items=[{"item_id": "item-002", "title": "Biryani", "quantity": 1}],
    )

    with SessionLocal() as db:
        result = build_ordering_intelligence(
            db,
            user_id,
            restaurant_name="Restaurant A",
        )

    assert result["orders_analyzed"] == 1
    assert result["usual_items"][0]["title"] == "Pizza"


def test_ai_ordering_context_is_compact():
    user_id, _ = signup_and_login()

    _create_order(
        user_id=user_id,
        restaurant_name="Restaurant A",
        items=[
            {"item_id": "item-001", "title": "Pizza", "quantity": 2},
            {"item_id": "item-002", "title": "Coke", "quantity": 1},
        ],
    )

    with SessionLocal() as db:
        context = build_ai_ordering_context(db, user_id)

    assert context["orders_analyzed"] == 1
    assert len(context["usual_items"]) <= 5
    assert len(context["favorite_restaurants"]) <= 3


def test_empty_ordering_intelligence():
    user_id, _ = signup_and_login()

    with SessionLocal() as db:
        result = build_ordering_intelligence(db, user_id)

    assert result["orders_analyzed"] == 0
    assert result["usual_items"] == []
    assert result["favorite_restaurants"] == []
    assert result["repeat_combinations"] == []
    assert result["latest_order"] is None


def test_smart_reorder_suggestions():
    user_id, _ = signup_and_login()

    _create_order(
        user_id=user_id,
        restaurant_name="Restaurant A",
        items=[{"item_id": "item-001", "title": "Biryani", "quantity": 1}],
    )
    _create_order(
        user_id=user_id,
        restaurant_name="Restaurant A",
        items=[{"item_id": "item-001", "title": "Biryani", "quantity": 1}],
    )

    with SessionLocal() as db:
        suggestions = build_smart_reorder_suggestions(db, user_id)

    assert suggestions
    assert suggestions[0]["title"] == "Biryani"
    assert suggestions[0]["order_count"] == 2
    assert suggestions[0]["score"] > 0
