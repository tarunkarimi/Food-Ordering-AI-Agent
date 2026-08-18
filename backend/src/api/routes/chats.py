from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import json

from src.agents.graph import chatbot_agent_builder


router = APIRouter()

# Build the chatbot agent once when the application starts.
chatbot_agent = chatbot_agent_builder()


class ChatRequest(BaseModel):
    user_message: str
    session_id: Optional[str]
    restaurant_name: str
    subdomain: str


@router.get("/state")
def get_current_state(session_id: str):
    """
    Return the current LangGraph state for a conversation session.
    """
    try:
        if not session_id or not session_id.strip():
            raise ValueError("session_id is missing.")

        config = {
            "configurable": {
                "thread_id": session_id.strip()
            }
        }

        state = chatbot_agent.get_state(config)

        return state

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )


@router.post("/orders")
async def chat_order(request: ChatRequest):
    """
    Process a user message through the food-ordering agent
    and stream AI responses using Server-Sent Events (SSE).
    """

    try:
        # -----------------------------
        # Validate request
        # -----------------------------

        if not request.session_id or not request.session_id.strip():
            raise ValueError("session_id is missing.")

        if not request.user_message or not request.user_message.strip():
            raise ValueError("user_message cannot be empty.")

        if not request.restaurant_name or not request.restaurant_name.strip():
            raise ValueError("restaurant_name is required.")

        if not request.subdomain or not request.subdomain.strip():
            raise ValueError("subdomain is required.")

        session_id = request.session_id.strip()
        user_message = request.user_message.strip()
        restaurant_name = request.restaurant_name.strip()
        subdomain = request.subdomain.strip()

        config = {
            "configurable": {
                "thread_id": session_id
            }
        }

        # -----------------------------
        # SSE generator
        # -----------------------------

        def generate_sse():
            try:
                events = chatbot_agent.stream(
                    {
                        "messages": [
                            {
                                "role": "user",
                                "content": user_message,
                            }
                        ],
                        "restaurant_name": restaurant_name,
                        "subdomain": subdomain,
                    },
                    config,
                    stream_mode="values",
                )

                for event in events:

                    # Ignore malformed/empty events safely.
                    if not event:
                        continue

                    messages = event.get("messages", [])

                    if not messages:
                        continue

                    last_message = messages[-1]

                    message_type = type(last_message).__name__

                    # -----------------------------
                    # Server-side logging
                    # -----------------------------

                    if message_type == "ToolMessage":

                        if getattr(last_message, "status", None) == "error":
                            print(
                                f"Tool error: {last_message.content}"
                            )
                        else:
                            content = str(
                                getattr(
                                    last_message,
                                    "content",
                                    ""
                                )
                            )

                            print(
                                f"ToolMessage: {content[:100]}..."
                            )

                    else:
                        content = str(
                            getattr(
                                last_message,
                                "content",
                                ""
                            )
                        )

                        print(
                            f"{message_type}: {content}"
                        )

                    # Log tool calls made by the AI.
                    if getattr(last_message, "type", None) == "ai":

                        tool_calls = getattr(
                            last_message,
                            "tool_calls",
                            []
                        )

                        if tool_calls:
                            print(
                                f"Tools called: {tool_calls}"
                            )

                    # -----------------------------
                    # Send AI messages to frontend
                    # -----------------------------

                    if message_type == "AIMessage":

                        content = getattr(
                            last_message,
                            "content",
                            ""
                        )

                        tool_calls = getattr(
                            last_message,
                            "tool_calls",
                            []
                        )

                        # Normalize content to string.
                        if content is None:
                            content = ""

                        if not isinstance(content, str):
                            content = str(content)

                        response_data = {
                            "type": "AIMessage",
                            "content": content,
                            "tool_calls": tool_calls,
                        }

                        # Only send messages containing
                        # actual textual content.
                        if content.strip():

                            yield (
                                f"data: "
                                f"{json.dumps(response_data, default=str)}"
                                f"\n\n"
                            )

                # -----------------------------
                # Stream completion signal
                # -----------------------------

                yield "data: [DONE]\n\n"

            except Exception as e:

                # Send the streaming error to the client
                # instead of silently terminating the stream.
                error_data = {
                    "type": "error",
                    "content": str(e),
                }

                yield (
                    f"data: "
                    f"{json.dumps(error_data)}"
                    f"\n\n"
                )

                yield "data: [DONE]\n\n"

        # -----------------------------
        # Return SSE response
        # -----------------------------

        return StreamingResponse(
            generate_sse(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
            },
        )

    except Exception as e:

        raise HTTPException(
            status_code=400,
            detail=str(e)
        )