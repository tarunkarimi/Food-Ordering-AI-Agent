"""Focused tests for AI integration with explicit user preferences."""

from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.nodes.chatbot import chatbot
from src.agents.nodes.tool_node import tool_node
from src.agents.tools.preferences import (
    get_my_preferences,
    update_my_preferences,
)
from tests.test_cart_tools import make_cart, make_state


def _state(user_id=123):
    state = make_state(make_cart())
    state.update(
        {
            "user_id": user_id,
            "restaurant_name": "Test Restaurant",
            "subdomain": "test",
        }
    )
    return state


def test_preference_tools_are_available():
    assert get_my_preferences.name == "get_my_preferences"
    assert update_my_preferences.name == "update_my_preferences"


def test_preference_tools_do_not_expose_user_id_as_model_argument():
    get_schema = get_my_preferences.args_schema.model_json_schema()
    update_schema = update_my_preferences.args_schema.model_json_schema()

    assert "user_id" not in get_schema.get("properties", {})
    assert "user_id" not in update_schema.get("properties", {})


def test_get_my_preferences_reads_authenticated_state_user():
    preferences = type(
        "Preferences",
        (),
        {
            "cuisine_preference": "South Indian",
            "spice_level": "hot",
            "dietary_preference": "Vegetarian",
            "meal_preference": "Dinner",
            "notes": "Prefer less oil.",
        },
    )()

    state = _state(123)

    with (
        patch(
            "src.agents.tools.preferences.get_user_preferences",
            return_value=preferences,
        ) as get_preferences,
    ):
        result = get_my_preferences.invoke(
            {"state": state}
        )

    get_preferences.assert_called_once()

    assert result["preferences"]["cuisine_preference"] == "South Indian"
    assert result["preferences"]["spice_level"] == "hot"
    assert result["preferences"]["dietary_preference"] == "Vegetarian"


def test_get_my_preferences_handles_missing_preferences():
    state = _state(123)

    with patch(
        "src.agents.tools.preferences.get_user_preferences",
        return_value=None,
    ):
        result = get_my_preferences.invoke(
            {"state": state}
        )

    assert result["preferences"] is None
    assert "saved food preferences" in result["message"]


def test_get_my_preferences_requires_authenticated_state():
    state = _state(None)

    result = get_my_preferences.invoke(
        {"state": state}
    )

    assert "sign in" in result["message"].lower()


def test_update_my_preferences_saves_authenticated_user_preferences():
    preferences = type(
        "Preferences",
        (),
        {
            "cuisine_preference": "South Indian",
            "spice_level": "hot",
            "dietary_preference": None,
            "meal_preference": None,
            "notes": None,
        },
    )()

    state = _state(123)

    with patch(
        "src.agents.tools.preferences.update_user_preferences",
        return_value=preferences,
    ) as update:
        result = update_my_preferences.invoke(
            {
                "state": state,
                "cuisine_preference": "South Indian",
                "spice_level": "hot",
            }
        )

    kwargs = update.call_args.kwargs

    assert kwargs == {
        "user_id": 123,
        "cuisine_preference": "South Indian",
        "spice_level": "hot",
        "dietary_preference": None,
        "meal_preference": None,
        "notes": None,
    }

    assert result["message"] == "Your food preferences have been saved."
    assert result["preferences"]["cuisine_preference"] == "South Indian"


def test_update_my_preferences_requires_authenticated_state():
    state = _state(None)

    result = update_my_preferences.invoke(
        {
            "state": state,
            "spice_level": "hot",
        }
    )

    assert "sign in" in result["message"].lower()


def test_chatbot_registers_preference_tools():
    import src.agents.nodes.chatbot as chatbot_module

    tool_names = [tool.name for tool in chatbot_module._tools]

    assert "get_my_preferences" in tool_names
    assert "update_my_preferences" in tool_names


def test_tool_node_dispatches_get_my_preferences():
    state = _state(123)

    state["messages"] = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "get_my_preferences",
                    "args": {},
                    "id": "preferences-read-1",
                    "type": "tool_call",
                }
            ],
        )
    ]

    expected_message = object()

    with patch(
        "src.agents.nodes.tool_node._single_tool_node.invoke",
        return_value={"messages": [expected_message]},
    ) as invoke:
        result = tool_node(state, config=None)

    invoke.assert_called_once()
    assert result["messages"] == [expected_message]


def test_tool_node_dispatches_update_my_preferences():
    state = _state(123)

    state["messages"] = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "update_my_preferences",
                    "args": {
                        "spice_level": "hot",
                    },
                    "id": "preferences-update-1",
                    "type": "tool_call",
                }
            ],
        )
    ]

    expected_message = object()

    with patch(
        "src.agents.nodes.tool_node._single_tool_node.invoke",
        return_value={"messages": [expected_message]},
    ) as invoke:
        result = tool_node(state, config=None)

    invoke.assert_called_once()
    assert result["messages"] == [expected_message]


def test_preferences_can_be_used_in_ai_roundtrip():
    state = _state(123)

    state["messages"] = [
        HumanMessage(
            content="What are my saved food preferences?"
        ),
        ToolMessage(
            content=(
                '{"preferences":{"cuisine_preference":"South Indian",'
                '"spice_level":"hot","dietary_preference":"Vegetarian",'
                '"meal_preference":"Dinner","notes":null}}'
            ),
            tool_call_id="preferences-roundtrip-1",
        ),
    ]

    model_response = AIMessage(
        content=(
            "Your saved preferences are South Indian food, hot spice "
            "levels, vegetarian options, and dinner."
        ),
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
        patch("src.agents.nodes.chatbot._model_with_tools", fake_model),
        patch("src.agents.nodes.chatbot._persist_cart") as persist_cart,
    ):
        result = chatbot(state)

    response = result["messages"][-1].content

    assert "South Indian" in response
    assert "hot" in response
    assert "vegetarian" in response.lower()
    assert result["cart"] == make_cart()
    persist_cart.assert_called_once()


def test_preference_read_does_not_modify_cart():
    state = _state(123)
    original_cart = state["cart"]

    model_response = AIMessage(
        content="I can use your saved preferences for recommendations.",
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
        patch("src.agents.nodes.chatbot._model_with_tools", fake_model),
        patch("src.agents.nodes.chatbot._persist_cart") as persist_cart,
    ):
        result = chatbot(state)

    assert result["cart"] == original_cart
    persist_cart.assert_called_once()
