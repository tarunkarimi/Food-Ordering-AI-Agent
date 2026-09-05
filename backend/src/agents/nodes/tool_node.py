from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
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
]


_single_tool_node = ToolNode(tools)


def _apply_result(state: dict[str, Any], result: Any) -> list[Any]:
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


def _latest_human_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            content = message.content

            if isinstance(content, str):
                return content.strip().lower()

            if isinstance(content, list):
                parts = []

                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        parts.append(str(part.get("text", "")))

                return " ".join(parts).strip().lower()

    return ""


def _is_explicit_confirmation(text: str) -> bool:
    normalized = " ".join(text.split())

    return normalized in {
        "yes",
        "yes please",
        "yes, please",
        "confirm",
        "confirm order",
        "confirmed",
        "place order",
        "place the order",
        "go ahead",
        "go ahead and place it",
        "proceed",
        "proceed with the order",
        "i confirm",
        "i confirm the order",
        "looks good",
        "looks good, place it",
        "that's correct",
        "that is correct",
        "correct",
        "yes, confirm",
        "yes, confirm the order",
    }


def tool_node(state, config=None):
    """
    Execute Gemini tool calls sequentially.

    Order confirmation is enforced deterministically:

    Turn 1:
        confirm_order -> allowed
        place_order   -> blocked

    Turn 2:
        explicit confirmation + pending confirmation
        -> redundant confirm_order is skipped
        -> place_order is allowed
    """

    messages = state.get("messages", [])

    if not messages:
        return {}

    last_message = messages[-1]

    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        return {}

    # Snapshot BEFORE any tool in this turn changes the state.
    confirmation_pending_at_start = bool(
        state.get("order_confirmation_pending", False)
    )

    latest_human_text = _latest_human_text(messages)
    explicit_confirmation = _is_explicit_confirmation(latest_human_text)

    working_state = dict(state)
    working_messages = list(messages)
    new_tool_messages: list[Any] = []

    for tool_call in last_message.tool_calls:
        tool_name = tool_call.get("name")
        tool_call_id = tool_call.get("id")

        # ---------------------------------------------------------
        # CONFIRM ORDER
        # ---------------------------------------------------------
        if (
            tool_name == "confirm_order"
            and confirmation_pending_at_start
            and explicit_confirmation
        ):
            tool_message = ToolMessage(
                content=(
                    "The customer has already explicitly confirmed "
                    "the order. Do not request confirmation again. "
                    "Proceed with placing the order."
                ),
                tool_call_id=tool_call_id,
            )

            new_tool_messages.append(tool_message)
            working_messages.append(tool_message)
            continue

        # ---------------------------------------------------------
        # PLACE ORDER
        # ---------------------------------------------------------
        if tool_name == "place_order":
            if not (
                confirmation_pending_at_start
                and explicit_confirmation
            ):
                tool_message = ToolMessage(
                    content=(
                        "ORDER_PLACEMENT_BLOCKED: The customer has not "
                        "explicitly confirmed the order in a separate "
                        "confirmation response. Do not place the order. "
                        "Ask the customer to confirm the displayed order."
                    ),
                    tool_call_id=tool_call_id,
                )

                new_tool_messages.append(tool_message)
                working_messages.append(tool_message)
                continue

        # ---------------------------------------------------------
        # NORMAL TOOL EXECUTION
        # ---------------------------------------------------------

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