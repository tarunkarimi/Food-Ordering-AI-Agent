import json
from uuid import uuid4
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.nodes.chatbot import chatbot, _tools
from src.agents.tools.personalization import get_my_food_preferences
from src.db.database import SessionLocal
from src.db.models import OrderHistory
from tests.test_authenticated_cart import signup_and_login


def _create_order(
    *,
    user_id: int,
    items: list[dict],
    restaurant_name: str = "Test Restaurant",
):
    with SessionLocal() as db:
        order = OrderHistory(
            user_id=user_id,
            order_id=f"PERSONALIZED-AI-{uuid4()}",
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
        "cart": None,
        "orderId": None,
        "order_status": None,
        "order_confirmation_pending": False,
        "restaurant_name": "Test Restaurant",
        "subdomain": "test",
        "user_id": user_id,
        "finished": False,
    }


def test_personalization_tool_is_registered_in_chatbot_tools():
    tool_names = {tool.name for tool in _tools}

    assert "get_my_food_preferences" in tool_names


def test_authenticated_chatbot_can_request_personalization():
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
        "id": "personalization-call-1",
        "type": "tool_call",
    }

    model_response = AIMessage(
        content="",
        tool_calls=[tool_call],
    )

    class FakeModelWithTools:
        def invoke(self, messages):
            return model_response

    with patch(
        "src.agents.nodes.chatbot._model_with_tools",
        new=FakeModelWithTools(),
    ):
        result = chatbot(
            _state(
                user_id,
                "What do I usually order?",
            )
        )

    assert result["user_id"] == user_id
    assert result["messages"][-1].tool_calls[0]["name"] == (
        "get_my_food_preferences"
    )
    assert result["messages"][-1].tool_calls[0]["args"]["user_id"] == user_id


def test_personalization_tool_reads_authenticated_user_history():
    user_id, _ = signup_and_login()

    _create_order(
        user_id=user_id,
        items=[
            {"title": "Chicken Biryani", "quantity": 2},
            {"title": "Coke", "quantity": 1},
        ],
    )

    result = get_my_food_preferences.invoke(
        {
            "user_id": user_id,
            "restaurant_name": "Test Restaurant",
        }
    )

    assert result["orders_analyzed"] == 1
    assert result["usual_items"][0]["title"] == "Chicken Biryani"
    assert result["usual_items"][0]["order_count"] == 1
    assert result["usual_items"][0]["total_quantity"] == 2


def test_personalization_tool_result_can_be_returned_as_tool_message():
    user_id, _ = signup_and_login()

    _create_order(
        user_id=user_id,
        items=[
            {"title": "Chicken Biryani", "quantity": 2},
        ],
    )

    result = get_my_food_preferences.invoke(
        {
            "user_id": user_id,
            "restaurant_name": "Test Restaurant",
        }
    )

    tool_message = ToolMessage(
        content=json.dumps(result),
        tool_call_id="personalization-call-2",
    )

    assert tool_message.tool_call_id == "personalization-call-2"
    assert "Chicken Biryani" in tool_message.content
