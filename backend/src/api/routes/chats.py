from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
import json
from pydantic import BaseModel
from typing import Optional
from src.agents.graph import chatbot_agent_builder

router = APIRouter()

# Define request body model

chatbot_agent = chatbot_agent_builder()


class ChatRequest(BaseModel):
    user_message: str
    session_id: Optional[str]
    restaurant_name: str
    subdomain: str


@router.get("/state")
def get_current_state(session_id: str):
    try:
        config = {"configurable": {"thread_id": session_id}}
        state = chatbot_agent.get_state(config)
        return state

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/orders")
async def chat_order(request: ChatRequest):
    try:
        if not request.session_id:
            raise ValueError("session_id is missing.")

        if not request.user_message or not request.user_message.strip():
            raise ValueError("user_message cannot be empty.")

        if not request.restaurant_name:
            raise ValueError("restaurant_name is required")

        if not request.subdomain:
            raise ValueError("subdomain is required")

        config = {"configurable": {"thread_id": request.session_id}}

        def generate_sse():
            events = chatbot_agent.stream(
                {"messages": [
                    {"role": "user", "content": request.user_message.strip()}],
                 "restaurant_name": request.restaurant_name,
                 "subdomain": request.subdomain,
                 },
                config,
                stream_mode="values",
            )

            for event in events:
                last_message = event['messages'][-1]

                # Log everything for debugging
                if type(last_message).__name__ == 'ToolMessage':
                    if last_message.status == "error":
                        print(last_message.content)
                    else:
                        print(
                            f"{type(last_message).__name__}: {last_message.content[:30]}...")
                else:
                    print(f"{type(last_message).__name__}: {last_message.content}")

                if last_message.type == "ai":
                    print(f"Tools called: ", last_message.tool_calls)

                # Only yield AIMessage content to the client
                if type(last_message).__name__ == 'AIMessage':
                    response_data = {
                        "type": "AIMessage",
                        "content": last_message.content if hasattr(last_message, 'content') else "",
                        "tool_calls": getattr(last_message, 'tool_calls', [])
                    }

                    # Only yield if there's actual content
                    if response_data["content"].strip():
                        yield f"data: {json.dumps(response_data)}\n\n"

            # Send end signal
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            generate_sse(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*"
            }
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

