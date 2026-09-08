"""Tests that the advanced recommendation is registered with LangGraph."""

from unittest.mock import patch

from langchain_core.messages import AIMessage

from src.agents.nodes.chatbot import chatbot


def test_advanced_recommendation_tool_is_registered():
    from src.agents.nodes import chatbot as chatbot_module

    names = [
        tool_obj.name
        for tool_obj in chatbot_module._tools
    ]

    assert "advanced_recommend_food" in names


def test_chatbot_can_request_advanced_recommendation():
    state = {
        "user_id": 123,
        "restaurant_name": "Test Restaurant",
        "subdomain": "test",
        "messages": [
            {
                "role": "user",
                "content": (
                    "I'm vegetarian and want something "
                    "spicy for dinner under ?300."
                ),
            }
        ],
        "cart": None,
    }

    model_response = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "advanced_recommend_food",
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
        == "advanced_recommend_food"
    )
