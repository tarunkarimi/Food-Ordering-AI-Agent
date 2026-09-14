"""Service boundary for LangGraph chat-agent execution."""

import json
import logging
from collections.abc import Iterator
from typing import Any

from src.agents.graph import chatbot_agent_builder

logger = logging.getLogger(__name__)


class ChatAgentService:
    """Owns construction and execution of the chat agent graph."""

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
        user_id: int | str,
        graph_config: dict[str, Any],
        agent: Any | None = None,
    ) -> Iterator[str]:
        """Stream an authenticated chat request as SSE events."""
        active_agent = agent or self.agent

        state = {
            "messages": [
                {
                    "role": "user",
                    "content": user_message,
                }
            ],
            "restaurant_name": restaurant_name,
            "subdomain": subdomain,
            "user_id": user_id,
        }

        try:
            events = active_agent.stream(
                state,
                graph_config,
                stream_mode="values",
            )

            for event in events:
                if not event:
                    continue

                messages = event.get("messages", [])

                if not messages:
                    continue

                last_message = messages[-1]
                message_type = type(last_message).__name__

                if message_type == "ToolMessage":
                    if getattr(last_message, "status", None) == "error":
                        logger.error(
                            "Tool execution failed for authenticated user %s.",
                            user_id,
                        )

                if getattr(last_message, "type", None) == "ai":
                    tool_calls = getattr(last_message, "tool_calls", [])

                    if tool_calls:
                        logger.info(
                            "AI requested tool execution for authenticated user %s.",
                            user_id,
                        )

                if message_type == "AIMessage":
                    content = getattr(last_message, "content", "")

                    tool_calls = getattr(
                        last_message,
                        "tool_calls",
                        [],
                    )

                    if content is None:
                        content = ""

                    if not isinstance(content, str):
                        content = str(content)

                    response_data = {
                        "type": "AIMessage",
                        "content": content,
                        "tool_calls": tool_calls,
                    }

                    if content.strip():
                        yield (
                            "data: "
                            + json.dumps(
                                response_data,
                                default=str,
                            )
                            + "\n\n"
                        )

            yield "data: [DONE]\n\n"

        except Exception:
            logger.exception(
                "Unexpected error while streaming AI response "
                "for authenticated user %s.",
                user_id,
            )

            error_data = {
                "type": "error",
                "content": (
                    "The AI service encountered an unexpected "
                    "error. Please try again."
                ),
            }

            yield (
                "data: "
                + json.dumps(error_data)
                + "\n\n"
            )

            yield "data: [DONE]\n\n"


chat_agent_service = ChatAgentService()
