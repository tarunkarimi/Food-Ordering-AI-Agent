import json
from uuid import uuid4
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.nodes.chatbot import chatbot
from src.agents.prompts.system_prompt import SYSTEM_INSTRUCTION
from src.db.database import SessionLocal
from src.db.models import OrderHistory
from tests.test_authenticated_cart import signup_and_login
from tests.test_cart_tools import make_cart


def _create_order(
    *,
    user_id: int,
    items: list[dict],
    restaurant_name: str = "Test Restaurant",
):
    with SessionLocal() as db:
        order = OrderHistory(
            user_id=user_id,
            order_id=f"PERSONALIZED-ROUNDTRIP-{uuid4()}",
            restaurant_name=restaurant_name,
            subdomain="test",
            status="confirmed",
            subtotal=500.0,
            total_items=sum(item["quantity"] for item in items),
            items_json=json.dumps(items),
        )
        db.add(order)
        db.commit()


def _state(user_id: int, message: str) -> dict:
    return {
        "messages": [HumanMessage(content=message)],
        "cart": make_cart(),
        "orderId": None,
        "order_status": None,
        "order_confirmation_pending": False,
        "restaurant_name": "Test Restaurant",
        "subdomain": "test",
        "user_id": user_id,
        "finished": False,
    }


def test_chatbot_personalization_round_trip_produces_natural_response():
    user_id, _ = signup_and_login()

    _create_order(
        user_id=user_id,
        items=[
            {"title": "Chicken Biryani", "quantity": 2},
            {"title": "Coke", "quantity": 1},
        ],
    )

    tool_call = {
        "name": "get_my_food_preferences",
        "args": {
            "user_id": user_id,
            "restaurant_name": "Test Restaurant",
        },
        "id": "personalization-roundtrip-1",
        "type": "tool_call",
    }

    tool_request = AIMessage(
        content="",
        tool_calls=[tool_call],
    )

    final_response = AIMessage(
        content=(
            "You usually order Chicken Biryani. "
            "You've ordered it in your previous orders, "
            "so it looks like one of your regular choices."
        )
    )

    class FakeModelWithTools:
        def __init__(self):
            self.calls = []

        def invoke(self, messages):
            self.calls.append(messages)

            if len(self.calls) == 1:
                return tool_request

            return final_response

    fake_model = FakeModelWithTools()

    with patch(
        "src.agents.nodes.chatbot._model_with_tools",
        new=fake_model,
    ):
        first_result = chatbot(
            _state(
                user_id,
                "What do I usually order?",
            )
        )

        tool_result = {
            "orders_analyzed": 1,
            "usual_items": [
                {
                    "title": "Chicken Biryani",
                    "order_count": 1,
                    "total_quantity": 2,
                }
            ],
            "last_order_items": [
                {
                    "title": "Chicken Biryani",
                    "quantity": 2,
                },
                {
                    "title": "Coke",
                    "quantity": 1,
                },
            ],
        }

        second_state = _state(
            user_id,
            "What do I usually order?",
        )
        second_state["messages"] = [
            HumanMessage(content="What do I usually order?"),
            tool_request,
            ToolMessage(
                content=json.dumps(tool_result),
                tool_call_id="personalization-roundtrip-1",
            ),
        ]

        second_result = chatbot(second_state)

    assert first_result["messages"][-1].tool_calls[0]["name"] == (
        "get_my_food_preferences"
    )

    assert isinstance(
        second_result["messages"][-1],
        AIMessage,
    )

    response = second_result["messages"][-1].content

    assert "Chicken Biryani" in response
    assert "usual" in response.lower()
    assert "orders_analyzed" not in response
    assert "order_count" not in response
    assert "total_quantity" not in response

    assert second_result["cart"] == make_cart()
