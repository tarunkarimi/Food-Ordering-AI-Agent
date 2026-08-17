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
from src.agents.tools.order import get_order_status


tools = [
    get_menu,
    get_cart,
    add_cart,
    remove_from_cart,
    clear_cart,
    place_order,
    confirm_order,
    get_order_status,
]

# Use LangGraph's ToolNode for injection/validation, but execute one
# tool call at a time so cart updates are applied sequentially.
_single_tool_node = ToolNode(tools)


def _apply_result(state: dict[str, Any], result: Any) -> list[Any]:
    """Apply a ToolNode result to local state and return tool messages."""
    messages: list[Any] = []

    if isinstance(result, Command):
        update = result.update or {}
        if isinstance(update, dict):
            for key in ("cart", "orderId", "finished"):
                if key in update:
                    state[key] = update[key]
            messages.extend(update.get("messages", []))
        return messages

    if isinstance(result, dict):
        for key in ("cart", "orderId", "finished"):
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
    """Execute Gemini tool calls sequentially.

    LangGraph 1.2.x returns a list when a ToolNode executes a tool that
    returns a Command. The previous implementation assumed a dictionary
    and therefore crashed with ``'list' object has no attribute 'get'``.

    This wrapper deliberately executes one call at a time and applies each
    Command's state update before running the next call. That prevents the
    cart from receiving concurrent updates while preserving ToolNode's
    InjectedState/InjectedToolCallId behavior.
    """
    messages = state.get("messages", [])
    if not messages:
        return {}

    last_message = messages[-1]
    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        return {}

    working_state = dict(state)
    working_messages = list(messages)
    new_tool_messages: list[Any] = []

    for tool_call in last_message.tool_calls:
        single_call_message = AIMessage(
            content=last_message.content,
            tool_calls=[tool_call],
        )

        working_state["messages"] = working_messages + [single_call_message]

        result = _single_tool_node.invoke(working_state, config=config)
        produced_messages = _apply_result(working_state, result)

        new_tool_messages.extend(produced_messages)
        working_messages.extend(produced_messages)

    return {
        "messages": new_tool_messages,
        "cart": working_state.get("cart"),
        "orderId": working_state.get("orderId"),
        "finished": working_state.get("finished", False),
    }
