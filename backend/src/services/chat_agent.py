"""Service boundary for LangGraph chat-agent execution."""

import json
import logging
import re
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.graph import chatbot_agent_builder
from src.observability.logging import log_event

logger = logging.getLogger(__name__)

_ORDER_SUCCESS_CLAIM = re.compile(
    r"\b(?:order|checkout)\b.{0,60}\b(?:placed|created|confirmed|successful|succeeded)\b"
    r"|\b(?:placed|created|confirmed|successful|succeeded)\b.{0,60}\b(?:order|checkout)\b",
    re.IGNORECASE | re.DOTALL,
)


def _content_to_text(content: Any) -> str:
    """Normalize LangChain/Gemini message content into displayable text."""
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []

        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue

            if isinstance(item, dict):
                text_value = item.get("text")
                if isinstance(text_value, str):
                    parts.append(text_value)
                    continue

                nested_content = item.get("content")
                if isinstance(nested_content, str):
                    parts.append(nested_content)

        return "\n".join(part for part in parts if part).strip()

    if isinstance(content, dict):
        text_value = content.get("text")
        if isinstance(text_value, str):
            return text_value.strip()

        nested_content = content.get("content")
        if isinstance(nested_content, str):
            return nested_content.strip()

    return str(content) if content is not None else ""


class ChatAgentService:
    """Owns construction and execution of the chat-agent graph."""

    def __init__(self, agent: Any | None = None) -> None:
        self.agent = agent or chatbot_agent_builder()

    def get_state(self, config: dict[str, Any]) -> Any:
        """Return the current graph state."""
        return self.agent.get_state(config)

    def update_state(
        self,
        config: dict[str, Any],
        values: dict[str, Any],
    ) -> Any:
        """Update graph state through the agent boundary."""
        return self.agent.update_state(config, values)

    def stream_response(
        self,
        *,
        user_message: str,
        restaurant_name: str,
        subdomain: str,
        user_id: int,
        graph_config: dict[str, Any],
        message_timestamp: datetime | None = None,
        agent: Any | None = None,
    ) -> Iterator[str]:
        """Stream agent responses as SSE events."""

        active_agent = agent or getattr(self, "agent", None)

        if active_agent is None:
            yield f"data: {json.dumps({
                "type": "error",
                "content": "The AI service encountered an unexpected error. Please try again.",
            })}\n\n"
            yield "data: [DONE]\n\n"
            return

        state = {
            "messages": [HumanMessage(content=user_message)],
            "cart": None,
            "orderId": None,
            "order_status": None,
            "order_history_persisted": False,
            "restaurant_name": restaurant_name,
            "subdomain": subdomain,
            "user_id": user_id,
            "finished": False,
        }

        run_config = dict(graph_config)
        metadata = dict(graph_config.get("metadata") or {})
        metadata["memory_message_timestamp"] = (
            message_timestamp or datetime.now(timezone.utc)
        ).isoformat()
        run_config["metadata"] = metadata

        checkout_attempted = False
        checkout_confirmed = False
        checkout_outcome_sent = False
        tool_names: dict[str, str] = {}
        seen_tool_call_ids: set[str] = set()

        try:
            for update in active_agent.stream(
                state,
                run_config,
                stream_mode="values",
            ):
                if not isinstance(update, dict):
                    continue

                messages = update.get("messages") or []
                if not messages:
                    continue

                checkout_confirmed = checkout_confirmed or (
                    checkout_attempted
                    and isinstance(update.get("orderId"), str)
                    and bool(update["orderId"].strip())
                    and update.get("order_status") == "confirmed"
                    and update.get("order_history_persisted") is True
                )

                current_turn_start = 0
                for index in range(len(messages) - 1, -1, -1):
                    message = messages[index]
                    if isinstance(message, HumanMessage) or getattr(message, "type", None) == "human":
                        current_turn_start = index + 1
                        break

                for message in messages[current_turn_start:]:
                    if not isinstance(message, AIMessage):
                        continue
                    for tool_call in message.tool_calls or []:
                        tool_name = tool_call.get("name")
                        tool_call_id = tool_call.get("id")
                        if tool_name == "place_order":
                            checkout_attempted = True
                            if (
                                isinstance(tool_call_id, str)
                                and tool_call_id not in seen_tool_call_ids
                            ):
                                checkout_confirmed = False
                                checkout_outcome_sent = False
                                seen_tool_call_ids.add(tool_call_id)
                        if isinstance(tool_call_id, str) and isinstance(tool_name, str):
                            tool_names[tool_call_id] = tool_name

                last_message = messages[-1]
                message_type = type(last_message).__name__
                langchain_type = getattr(last_message, "type", None)

                if (
                    isinstance(last_message, ToolMessage)
                    or message_type == "ToolMessage"
                    or langchain_type == "tool"
                ):
                    content = _content_to_text(
                        getattr(last_message, "content", "")
                    )
                    tool_call_id = getattr(last_message, "tool_call_id", None)
                    if tool_names.get(tool_call_id) == "place_order":
                        if checkout_confirmed:
                            order_id = update["orderId"].strip()
                            customer_message = (
                                f"Order {order_id} is confirmed and saved in My Orders."
                            )
                            log_event(logger, "chat.checkout.confirmed", authenticated=True)
                        else:
                            customer_message = content or (
                                "I could not confirm the order. Your cart is still saved. "
                                "Please retry the same confirmation."
                            )
                            log_event(
                                logger,
                                "chat.checkout.not_confirmed",
                                level=logging.WARNING,
                                authenticated=True,
                            )
                        yield f"data: {json.dumps({
                            "type": "AIMessage",
                            "content": customer_message,
                        })}\n\n"
                        checkout_outcome_sent = True
                    else:
                        yield f"data: {json.dumps({
                            "type": "tool",
                            "content": content,
                        })}\n\n"

                elif (
                    isinstance(last_message, AIMessage)
                    or message_type == "AIMessage"
                    or langchain_type == "ai"
                ):
                    content = _content_to_text(
                        getattr(last_message, "content", "")
                    )

                    if checkout_attempted and checkout_outcome_sent:
                        continue

                    if checkout_attempted and not checkout_confirmed:
                        if not checkout_outcome_sent:
                            yield f"data: {json.dumps({
                                "type": "AIMessage",
                                "content": (
                                    "I could not confirm the order. Your cart is still saved. "
                                    "Please retry the same confirmation."
                                ),
                            })}\n\n"
                            checkout_outcome_sent = True
                        continue

                    if not checkout_confirmed and _ORDER_SUCCESS_CLAIM.search(content):
                        # Model text alone is never evidence of a durable order.
                        # Keep confirmation in the explicit user-controlled flow.
                        content = (
                            "Your order summary is ready. Reply yes to confirm, "
                            "or tell me what you would like to change."
                        )

                    if content:
                        yield f"data: {json.dumps({
                            "type": "AIMessage",
                            "content": content,
                        })}\n\n"

        except Exception as exc:
            log_event(
                logger,
                "chat.stream_failed",
                level=logging.ERROR,
                authenticated=True,
                error_type=type(exc).__name__,
            )
            yield f"data: {json.dumps({
                "type": "error",
                "content": (
                    "I could not confirm the order. Your cart is still saved. "
                    "Please retry the same confirmation."
                    if checkout_attempted and not checkout_confirmed
                    else "The AI service encountered an unexpected error. Please try again."
                ),
            })}\n\n"

        finally:
            yield "data: [DONE]\n\n"


# Shared chat-agent service instance used by the API routes.
chat_agent_service = ChatAgentService()
