import json
from uuid import uuid4

from src.db.database import SessionLocal
from src.db.models import OrderHistory
from src.agents.tools.personalization import get_my_food_preferences
from src.services.personalization import get_personalization_summary
from tests.test_authenticated_cart import signup_and_login


def _create_order(
    *,
    user_id: int,
    order_id: str,
    restaurant_name: str,
    items: list[dict],
):
    with SessionLocal() as db:
        order = OrderHistory(
            user_id=user_id,
            order_id=order_id,
            restaurant_name=restaurant_name,
            subdomain="test",
            status="confirmed",
            subtotal=500.0,
            total_items=sum(item["quantity"] for item in items),
            items_json=json.dumps(items),
        )
        db.add(order)
        db.commit()
        db.refresh(order)
        return order.id


def test_personalization_summary_aggregates_order_items():
    user_id, _ = signup_and_login()

    _create_order(
        user_id=user_id,
        order_id=f"PERSONALIZATION-{uuid4()}-1",
        restaurant_name="Test Restaurant",
        items=[
            {"title": "Chicken Biryani", "quantity": 2},
            {"title": "Coke", "quantity": 1},
        ],
    )

    _create_order(
        user_id=user_id,
        order_id=f"PERSONALIZATION-{uuid4()}-2",
        restaurant_name="Test Restaurant",
        items=[
            {"title": "Chicken Biryani", "quantity": 1},
            {"title": "Coke", "quantity": 2},
        ],
    )

    with SessionLocal() as db:
        result = get_personalization_summary(
            db,
            user_id=user_id,
            restaurant_name="Test Restaurant",
        )

    assert result["orders_analyzed"] == 2
    assert result["usual_items"][0] == {
        "title": "Chicken Biryani",
        "order_count": 2,
        "total_quantity": 3,
    }
    assert {
        "title": "Coke",
        "order_count": 2,
        "total_quantity": 3,
    } in result["usual_items"]


def test_personalization_is_restaurant_scoped():
    user_id, _ = signup_and_login()

    _create_order(
        user_id=user_id,
        order_id=f"PERSONALIZATION-{uuid4()}-3",
        restaurant_name="Test Restaurant",
        items=[{"title": "Chicken Biryani", "quantity": 2}],
    )

    _create_order(
        user_id=user_id,
        order_id=f"PERSONALIZATION-{uuid4()}-4",
        restaurant_name="Other Restaurant",
        items=[{"title": "Pizza", "quantity": 3}],
    )

    with SessionLocal() as db:
        result = get_personalization_summary(
            db,
            user_id=user_id,
            restaurant_name="Test Restaurant",
        )

    assert result["orders_analyzed"] == 1
    assert result["usual_items"] == [
        {
            "title": "Chicken Biryani",
            "order_count": 1,
            "total_quantity": 2,
        }
    ]


def test_personalization_tool_requires_authentication():
    result = get_my_food_preferences.invoke(
        {
            "user_id": 0,
            "restaurant_name": "Test Restaurant",
        }
    )

    assert "sign in" in result["message"].lower()


def test_personalization_tool_does_not_modify_cart():
    assert "does not modify the cart" in get_my_food_preferences.description
    assert "place an order" in get_my_food_preferences.description
