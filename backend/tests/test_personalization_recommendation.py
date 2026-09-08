from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage

from src.agents.nodes.chatbot import chatbot
from tests.test_cart_tools import make_cart, make_state


def test_recommendation_model_requests_personalization_and_current_menu():
    state = make_state(make_cart())
    state.update(
        {
            "user_id": 123,
            "restaurant_name": "Test Restaurant",
            "subdomain": "test",
            "messages": [
                HumanMessage(
                    content="Recommend something based on my orders."
                )
            ],
        }
    )

    model_response = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "get_my_food_preferences",
                "args": {
                    "user_id": 123,
                    "restaurant_name": "Test Restaurant",
                },
                "id": "recommendation-preferences-1",
                "type": "tool_call",
            },
            {
                "name": "get_menu",
                "args": {},
                "id": "recommendation-menu-1",
                "type": "tool_call",
            },
        ],
    )

    fake_model = type(
        "FakeModel",
        (),
        {
            "invoke": lambda self, messages: model_response,
        },
    )()

    with (
        patch(
            "src.agents.nodes.chatbot._model_with_tools",
            fake_model,
        ),
        patch(
            "src.agents.nodes.chatbot._persist_cart",
        ) as persist_cart,
    ):
        result = chatbot(state)

    tool_calls = result["messages"][-1].tool_calls
    tool_names = [call["name"] for call in tool_calls]

    assert "get_my_food_preferences" in tool_names
    assert "get_menu" in tool_names

    assert "add_cart" not in tool_names
    assert "place_order" not in tool_names
    assert "confirm_order" not in tool_names

    persist_cart.assert_called_once()


def test_recommendation_does_not_require_cart_mutation():
    state = make_state(make_cart())
    state.update(
        {
            "user_id": 123,
            "restaurant_name": "Test Restaurant",
            "subdomain": "test",
            "messages": [
                HumanMessage(
                    content="Recommend something based on my orders."
                )
            ],
        }
    )

    model_response = AIMessage(
        content="Based on your previous orders, Chicken Biryani looks like a good choice.",
        tool_calls=[],
    )

    fake_model = type(
        "FakeModel",
        (),
        {
            "invoke": lambda self, messages: model_response,
        },
    )()

    with (
        patch(
            "src.agents.nodes.chatbot._model_with_tools",
            fake_model,
        ),
        patch(
            "src.agents.nodes.chatbot._persist_cart",
        ) as persist_cart,
    ):
        result = chatbot(state)

    assert result["messages"][-1].content
    assert result["cart"] == make_cart()

    persist_cart.assert_called_once()
