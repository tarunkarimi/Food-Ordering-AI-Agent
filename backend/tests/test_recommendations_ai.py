"""Tests for the personalized recommendation AI tool."""

from unittest.mock import patch

from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from src.agents.nodes.chatbot import chatbot
from src.agents.tools.recommendations import (
    get_personalized_recommendations,
)


def test_recommendation_tool_requires_authentication():
    state = {
        "user_id": None,
        "subdomain": "test",
        "restaurant_name": "Test Restaurant",
    }

    result = get_personalized_recommendations.invoke(
        {"state": state},
    )

    assert "sign in" in result["message"].lower()


def test_recommendation_tool_uses_current_menu():
    state = {
        "user_id": 123,
        "subdomain": "test",
        "restaurant_name": "Test Restaurant",
    }

    with (
        patch(
            "src.agents.tools.recommendations._fetch_menu_items",
            return_value=(
                [
                    {
                        "id": "1",
                        "title": "Chicken Biryani",
                        "base_price": 250,
                    }
                ],
                None,
            ),
        ),
        patch(
            "src.agents.tools.recommendations.SessionLocal"
        ) as session_local,
        patch(
            "src.agents.tools.recommendations.get_personalized_recommendations",
            return_value={
                "recommendations": [
                    {
                        "item_id": "1",
                        "title": "Chicken Biryani",
                        "current_price": 250.0,
                        "score": 5,
                        "reasons": ["matches your preferences"],
                    }
                ],
                "preferences_used": True,
                "orders_analyzed": 2,
            },
        ),
    ):
        session = session_local.return_value.__enter__.return_value

        result = get_personalized_recommendations.invoke(
            {"state": state},
        )

    assert result["recommendations"][0]["title"] == "Chicken Biryani"
    assert result["recommendations"][0]["current_price"] == 250.0
    session.close.assert_not_called()


def test_recommendation_tool_does_not_modify_cart():
    state = {
        "user_id": 123,
        "subdomain": "test",
        "restaurant_name": "Test Restaurant",
        "cart": {"items": []},
    }

    with (
        patch(
            "src.agents.tools.recommendations._fetch_menu_items",
            return_value=(
                [
                    {
                        "id": "1",
                        "title": "Dosa",
                        "base_price": 150,
                    }
                ],
                None,
            ),
        ),
        patch(
            "src.agents.tools.recommendations.SessionLocal"
        ) as session_local,
        patch(
            "src.agents.tools.recommendations.get_personalized_recommendations",
            return_value={
                "recommendations": [
                    {
                        "item_id": "1",
                        "title": "Dosa",
                        "current_price": 150.0,
                        "score": 5,
                        "reasons": [],
                    }
                ]
            },
        ),
    ):
        result = get_personalized_recommendations.invoke(
            {"state": state},
        )

    assert result["recommendations"]
    assert state["cart"] == {"items": []}


def test_chatbot_registers_advanced_recommendation_tool():
    from src.agents.nodes import chatbot as chatbot_module

    names = [
        tool_obj.name
        for tool_obj in chatbot_module._tools
    ]

    assert "get_personalized_recommendations" in names


def test_chatbot_can_request_advanced_recommendation():
    state = {
        "user_id": 123,
        "restaurant_name": "Test Restaurant",
        "subdomain": "test",
        "messages": [
            {
                "role": "user",
                "content": "What should I get today?",
            }
        ],
        "cart": None,
    }

    model_response = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "get_personalized_recommendations",
                "args": {},
                "id": "advanced-recommendation-1",
                "type": "tool_call",
            }
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
            "src.agents.nodes.chatbot._load_persistent_cart",
            return_value={"items": []},
        ),
        patch(
            "src.agents.nodes.chatbot._persist_cart",
        ),
    ):
        result = chatbot(state)

    assert (
        result["messages"][-1].tool_calls[0]["name"]
        == "get_personalized_recommendations"
    )
