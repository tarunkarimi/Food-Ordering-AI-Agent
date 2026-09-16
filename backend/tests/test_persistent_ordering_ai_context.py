from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage

from src.agents.nodes.chatbot import (
    _load_persistent_ordering_context,
    chatbot,
)


def _state(user_id, message="Recommend something for me."):
    return {
        "messages": [
            HumanMessage(content=message),
        ],
        "cart": None,
        "orderId": None,
        "order_status": None,
        "order_confirmation_pending": False,
        "restaurant_name": "Test Restaurant",
        "subdomain": "test",
        "user_id": user_id,
        "finished": False,
    }


def test_authenticated_user_loads_persistent_ordering_context():
    state = _state(123)

    expected = {
        "ordering_history": {
            "total_orders": 8,
            "total_items": 19,
            "total_spend": 4200.0,
            "average_order_value": 525.0,
            "last_order_id": "ORDER-8",
            "last_order_at": "2026-09-15T19:00:00",
            "weekday_patterns": {
                "saturday": 4,
                "sunday": 3,
                "monday": 1,
            },
            "meal_period_patterns": {
                "dinner": 6,
                "lunch": 2,
            },
            "favorite_items": [
                {
                    "item_key": "biryani-1",
                    "item_title": "Chicken Biryani",
                    "restaurant_name": "Test Restaurant",
                    "order_count": 6,
                    "total_quantity": 9,
                }
            ],
            "favorite_restaurants": [
                {
                    "restaurant_name": "Test Restaurant",
                    "order_count": 8,
                    "total_spend": 4200.0,
                }
            ],
        }
    }

    with patch(
        "src.agents.nodes.chatbot.SessionLocal"
    ) as session_local, patch(
        "src.agents.nodes.chatbot.build_persistent_ai_ordering_context",
        return_value=expected,
    ) as build_context:
        result = _load_persistent_ordering_context(state)

    assert result == expected
    build_context.assert_called_once()

    args, kwargs = build_context.call_args

    assert kwargs["user_id"] == 123
    assert kwargs["restaurant_name"] == "Test Restaurant"

    session_local.return_value.__enter__.assert_called_once()


def test_anonymous_user_does_not_load_persistent_ordering_context():
    state = _state(None)

    with patch(
        "src.agents.nodes.chatbot.build_persistent_ai_ordering_context"
    ) as build_context:
        result = _load_persistent_ordering_context(state)

    assert result == {}
    build_context.assert_not_called()


def test_chatbot_injects_persistent_context_into_model():
    state = _state(456)

    persistent_context = {
        "ordering_history": {
            "total_orders": 5,
            "total_items": 12,
            "total_spend": 2500.0,
            "average_order_value": 500.0,
            "last_order_id": "ORDER-5",
            "last_order_at": "2026-09-15T20:00:00",
            "weekday_patterns": {
                "saturday": 3,
                "monday": 2,
            },
            "meal_period_patterns": {
                "dinner": 4,
                "lunch": 1,
            },
            "favorite_items": [
                {
                    "item_key": "biryani-1",
                    "item_title": "Chicken Biryani",
                    "restaurant_name": "Test Restaurant",
                    "order_count": 4,
                    "total_quantity": 7,
                }
            ],
            "favorite_restaurants": [
                {
                    "restaurant_name": "Test Restaurant",
                    "order_count": 5,
                    "total_spend": 2500.0,
                }
            ],
        }
    }

    model_response = AIMessage(
        content="Based on your previous orders, Chicken Biryani looks like a good choice."
    )

    captured_messages = []

    class FakeModel:
        def invoke(self, messages):
            captured_messages.extend(messages)
            return model_response

    with patch(
        "src.agents.nodes.chatbot._model_with_tools",
        new=FakeModel(),
    ), patch(
        "src.agents.nodes.chatbot._load_persistent_cart",
        return_value={"items": []},
    ), patch(
        "src.agents.nodes.chatbot._load_persistent_ordering_context",
        return_value=persistent_context,
    ), patch(
        "src.agents.nodes.chatbot._persist_cart",
    ):
        result = chatbot(state)

    assert result["messages"][-1].content == model_response.content

    assert len(captured_messages) == 3

    context_message = captured_messages[1]

    assert context_message[0] == "system"
    assert "PERSISTENT ORDERING CONTEXT" in context_message[1]
    assert "Chicken Biryani" in context_message[1]
    assert "Test Restaurant" in context_message[1]
    assert "total_orders" in context_message[1]
    assert "Current menu data remains authoritative" in context_message[1]

    customer_message = captured_messages[2]

    assert customer_message.content == "Recommend something for me."


def test_chatbot_without_persistent_context_preserves_normal_message_flow():
    state = _state(789)

    model_response = AIMessage(
        content="Here are some options from the menu."
    )

    captured_messages = []

    class FakeModel:
        def invoke(self, messages):
            captured_messages.extend(messages)
            return model_response

    with patch(
        "src.agents.nodes.chatbot._model_with_tools",
        new=FakeModel(),
    ), patch(
        "src.agents.nodes.chatbot._load_persistent_cart",
        return_value={"items": []},
    ), patch(
        "src.agents.nodes.chatbot._load_persistent_ordering_context",
        return_value={},
    ), patch(
        "src.agents.nodes.chatbot._persist_cart",
    ):
        result = chatbot(state)

    assert result["messages"][-1].content == model_response.content
    assert len(captured_messages) == 2
    assert captured_messages[0][0] == "system"
    assert captured_messages[1].content == "Recommend something for me."
