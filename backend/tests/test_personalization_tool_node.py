from unittest.mock import patch

from langchain_core.messages import AIMessage

from src.agents.nodes.tool_node import tool_node
from tests.test_cart_tools import make_cart, make_state


def test_tool_node_dispatches_personalization_tool_call():
    state = make_state(make_cart())
    state.update(
        {
            "user_id": 123,
            "restaurant_name": "Test Restaurant",
            "subdomain": "test",
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "get_my_food_preferences",
                            "args": {
                                "user_id": 123,
                                "restaurant_name": "Test Restaurant",
                            },
                            "id": "personalization-tool-node-1",
                            "type": "tool_call",
                        }
                    ],
                )
            ],
        }
    )

    expected_message = object()

    with patch(
        "src.agents.nodes.tool_node._single_tool_node.invoke",
        return_value={
            "messages": [expected_message],
        },
    ) as invoke:
        result = tool_node(
            state,
            config=None,
        )

    invoke.assert_called_once()

    assert result["messages"] == [expected_message]
