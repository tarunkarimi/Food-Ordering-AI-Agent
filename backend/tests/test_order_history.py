"""Focused tests for authenticated persistent order history."""

from datetime import datetime, timezone

from src.db.models import OrderHistory
from src.services.order_history_serializer import serialize_order_history


def test_order_history_serializes_items():
    order = OrderHistory(
        id=1,
        user_id=10,
        order_id="ORD-001",
        restaurant_name="Test Restaurant",
        subdomain="test",
        status="confirmed",
        subtotal=440.00,
        total_items=2,
        items_json=(
            '[{"item_id":"item-001","title":"Chicken Biryani",'
            '"quantity":2,"base_price":220.0,"variation":null}]'
        ),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    result = serialize_order_history(order)

    assert result["id"] == 1
    assert result["order_id"] == "ORD-001"
    assert result["restaurant_name"] == "Test Restaurant"
    assert result["subdomain"] == "test"
    assert result["status"] == "confirmed"
    assert result["subtotal"] == 440.0
    assert result["total_items"] == 2
    assert result["items"][0]["item_id"] == "item-001"
    assert result["items"][0]["quantity"] == 2


def test_order_history_serializer_handles_invalid_items_json():
    order = OrderHistory(
        id=2,
        user_id=10,
        order_id="ORD-002",
        restaurant_name="Test Restaurant",
        subdomain="test",
        status="confirmed",
        subtotal=220.00,
        total_items=1,
        items_json="not-valid-json",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    result = serialize_order_history(order)

    assert result["items"] == []


def test_order_history_model_has_user_ownership():
    assert OrderHistory.user_id.property.columns[0].nullable is False
    assert OrderHistory.order_id.property.columns[0].unique is True
