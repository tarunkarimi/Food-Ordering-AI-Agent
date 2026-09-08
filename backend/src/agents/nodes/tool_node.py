from typing import Any

from langchain_core.messages import AIMessage
from langgraph.prebuilt import ToolNode
from langgraph.types import Command

from src.agents.tools.cart import (
    get_menu,
    get_cart,
    add_cart,
    remove_from_cart,
    clear_cart,
    place_order,
    confirm_order,
)
from src.agents.tools.order import cancel_order, get_order_status
from src.agents.tools.reorder import reorder_previous_order
from src.agents.tools.personalization import get_my_food_preferences


tools = [
    get_menu,
    get_cart,
    add_cart,
    remove_from_cart,
    clear_cart,
    place_order,
    confirm_order,
    get_order_status,
    cancel_order,
    reorder_previous_order,
        get_my_food_preferences,
]


# ToolNode remains responsible for:
# - Pydantic argument validation
# - InjectedState
# - InjectedToolCallId
#
# We execute calls sequentially so multiple cart mutations from one
# model response see the state produced by the previous mutation.
_single_tool_node = ToolNode(tools)


def _apply_result(state: dict[str, Any], result: Any) -> list[Any]:
    """Apply a ToolNode result to local state and return tool messages."""
    messages: list[Any] = []

    if isinstance(result, Command):
        update = result.update or {}

        if isinstance(update, dict):
            for key in (
                "cart",
                "orderId",
                "order_status",
                "order_confirmation_pending",
                "finished",
            ):
                if key in update:
                    state[key] = update[key]

            messages.extend(update.get("messages", []))

        return messages

    if isinstance(result, dict):
        for key in (
            "cart",
            "orderId",
            "order_status",
            "order_confirmation_pending",
            "finished",
        ):
            if key in result:
                state[key] = result[key]

        messages.extend(result.get("messages", []))
        return messages

    if isinstance(result, list):
        for item in result:
            messages.extend(_apply_result(state, item))

        return messages

    return messages


def tool_node(state, config=None):
    """
    Execute Gemini tool calls sequentially.

    LangGraph's ToolNode performs argument validation and injected
    argument handling. This wrapper only controls sequential execution
    and applies each tool's state update before the next tool runs.
    """
    messages = state.get("messages", [])

    if not messages:
        return {}

    last_message = messages[-1]

    if not isinstance(last_message, AIMessage):
        return {}

    tool_calls = last_message.tool_calls

    if not tool_calls:
        return {}

    working_state = dict(state)
    working_messages = list(messages)
    new_tool_messages: list[Any] = []

    for tool_call in tool_calls:
        single_call_message = AIMessage(
            content=last_message.content,
            tool_calls=[tool_call],
        )

        working_state["messages"] = working_messages + [
            single_call_message
        ]

        result = _single_tool_node.invoke(
            working_state,
            config=config,
        )

        produced_messages = _apply_result(
            working_state,
            result,
        )

        new_tool_messages.extend(produced_messages)
        working_messages.extend(produced_messages)

    return {
        "messages": new_tool_messages,
        "cart": working_state.get("cart"),
        "orderId": working_state.get("orderId"),
        "order_status": working_state.get("order_status"),
        "order_confirmation_pending": working_state.get(
            "order_confirmation_pending",
            False,
        ),
        "finished": working_state.get("finished", False),
    }

