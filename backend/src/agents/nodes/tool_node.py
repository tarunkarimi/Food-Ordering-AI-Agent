"""LangGraph tool execution node."""

import logging
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
from src.agents.tools.preferences import (
    get_my_preferences,
    update_my_preferences,
)
from src.agents.tools.recommendations import get_personalized_recommendations
from src.agents.tools.advanced_recommendation import advanced_recommend_food
from src.agents.tools.testing import (
    generate_ai_test_cases,
    generate_ai_edge_cases,
    analyze_ai_test_failure,
    recommend_ai_regression_tests,
)
from src.observability.logging import Timer, log_event


logger = logging.getLogger(__name__)


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
    get_my_preferences,
    update_my_preferences,
    get_personalized_recommendations,
    advanced_recommend_food,
    generate_ai_test_cases,
    generate_ai_edge_cases,
    analyze_ai_test_failure,
    recommend_ai_regression_tests,
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
            messages.extend(
                _apply_result(state, item)
            )

        return messages

    return messages


def tool_node(state, config=None):
    """Execute Gemini tool calls sequentially."""

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
        tool_name = tool_call.get(
            "name",
            "unknown",
        )

        single_call_message = AIMessage(
            content=last_message.content,
            tool_calls=[tool_call],
        )

        working_state["messages"] = (
            working_messages + [single_call_message]
        )

        timer = Timer()

        log_event(
            logger,
            "agent_tool_started",
            tool_name=tool_name,
            authenticated=working_state.get("user_id") is not None,
        )

        try:
            result = _single_tool_node.invoke(
                working_state,
                config=config,
            )

            produced_messages = _apply_result(
                working_state,
                result,
            )

            log_event(
                logger,
                "agent_tool_completed",
                tool_name=tool_name,
                authenticated=working_state.get("user_id") is not None,
                duration_ms=timer.elapsed_ms,
            )

        except Exception:
            log_event(
                logger,
                "agent_tool_failed",
                level=logging.ERROR,
                tool_name=tool_name,
                authenticated=working_state.get("user_id") is not None,
                duration_ms=timer.elapsed_ms,
            )
            raise

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

