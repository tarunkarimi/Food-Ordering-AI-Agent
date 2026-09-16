import json
from datetime import datetime
from uuid import uuid4

from src.db.database import SessionLocal
from src.db.models.order_history import OrderHistory
from src.db.models.ordering_processed_order import UserOrderingProcessedOrder
from src.services.persistent_ordering_intelligence import (
    build_persistent_ai_ordering_context,
    get_persistent_ordering_profile,
    record_order_intelligence,
)

from tests.test_authenticated_cart import signup_and_login


def _create_order(
    db,
    user_id,
    restaurant,
    items,
    subtotal,
    created_at,
):
    order = OrderHistory(
        user_id=user_id,
        order_id=f"intel-order-{uuid4().hex}",
        restaurant_name=restaurant,
        subdomain="test",
        status="confirmed",
        subtotal=subtotal,
        total_items=sum(item["quantity"] for item in items),
        items_json=json.dumps(items),
        created_at=created_at,
    )
    db.add(order)
    db.flush()
    return order


def test_record_order_intelligence_builds_profile():
    user_id, _ = signup_and_login()

    with SessionLocal() as db:
        first = _create_order(
            db,
            user_id,
            "Andhra Kitchen",
            [
                {
                    "item_id": "biryani-1",
                    "title": "Chicken Biryani",
                    "quantity": 2,
                },
                {
                    "item_id": "naan-1",
                    "title": "Butter Naan",
                    "quantity": 1,
                },
            ],
            450,
            datetime(2026, 9, 14, 13, 30),
        )

        second = _create_order(
            db,
            user_id,
            "Andhra Kitchen",
            [
                {
                    "item_id": "biryani-1",
                    "title": "Chicken Biryani",
                    "quantity": 1,
                }
            ],
            250,
            datetime(2026, 9, 15, 20, 30),
        )

        record_order_intelligence(db, user_id, first)
        record_order_intelligence(db, user_id, second)
        db.commit()

        profile = get_persistent_ordering_profile(
            db,
            user_id=user_id,
        )

        assert profile["total_orders"] == 2
        assert profile["total_items"] == 4
        assert profile["total_spend"] == 700.0
        assert profile["average_order_value"] == 350.0
        assert profile["last_order_id"] == second.order_id

        assert profile["weekday_patterns"]["monday"] == 1
        assert profile["weekday_patterns"]["tuesday"] == 1

        assert profile["meal_period_patterns"]["lunch"] == 1
        assert profile["meal_period_patterns"]["dinner"] == 1

        assert profile["favorite_items"][0]["item_title"] == "Chicken Biryani"
        assert profile["favorite_items"][0]["order_count"] == 2
        assert profile["favorite_items"][0]["total_quantity"] == 3

        assert (
            profile["favorite_restaurants"][0]["restaurant_name"]
            == "Andhra Kitchen"
        )
        assert profile["favorite_restaurants"][0]["order_count"] == 2


def test_record_order_intelligence_is_idempotent():
    user_id, _ = signup_and_login()

    with SessionLocal() as db:
        order = _create_order(
            db,
            user_id,
            "Test Restaurant",
            [
                {
                    "item_id": "item-1",
                    "title": "Test Item",
                    "quantity": 2,
                }
            ],
            200,
            datetime(2026, 9, 15, 19, 0),
        )

        record_order_intelligence(db, user_id, order)
        record_order_intelligence(db, user_id, order)
        db.commit()

        profile = get_persistent_ordering_profile(
            db,
            user_id=user_id,
        )

        assert profile["total_orders"] == 1
        assert profile["total_items"] == 2
        assert profile["total_spend"] == 200.0

        processed = db.query(
            UserOrderingProcessedOrder
        ).filter(
            UserOrderingProcessedOrder.user_id == user_id,
            UserOrderingProcessedOrder.order_id == order.order_id,
        ).all()

        assert len(processed) == 1


def test_empty_profile_has_empty_ai_context():
    user_id, _ = signup_and_login()

    with SessionLocal() as db:
        context = build_persistent_ai_ordering_context(
            db,
            user_id=user_id,
        )

        assert context["ordering_history"]["total_orders"] == 0
        assert context["favorite_items"] == []
        assert context["favorite_restaurants"] == []
        assert context["weekday_patterns"] == {}
        assert context["meal_period_patterns"] == {}


def test_record_order_intelligence_duplicate_insert_is_safe():
    user_id, _ = signup_and_login()

    with SessionLocal() as db:
        order = _create_order(
            db,
            user_id,
            "Concurrency Restaurant",
            [
                {
                    "item_id": "item-concurrent",
                    "title": "Concurrent Item",
                    "quantity": 2,
                }
            ],
            300,
            datetime(2026, 9, 15, 19, 30),
        )

        record_order_intelligence(db, user_id, order)
        db.commit()

        record_order_intelligence(db, user_id, order)
        db.commit()

        profile = get_persistent_ordering_profile(
            db,
            user_id=user_id,
        )

        assert profile["total_orders"] == 1
        assert profile["total_items"] == 2
        assert profile["total_spend"] == 300.0

        processed_count = (
            db.query(UserOrderingProcessedOrder)
            .filter(
                UserOrderingProcessedOrder.user_id == user_id,
                UserOrderingProcessedOrder.order_id == order.order_id,
            )
            .count()
        )

        assert processed_count == 1
