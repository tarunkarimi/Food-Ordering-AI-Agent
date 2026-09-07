"""Authentication-to-LangGraph identity binding tests."""

from uuid import uuid4
from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from src.main import app

from tests.test_authenticated_cart import (
    auth_headers,
    signup_and_login,
)


client = TestClient(app)


def _chat_payload(session_id: str = "same-session") -> dict:
    return {
        "user_message": "Hello",
        "session_id": session_id,
        "restaurant_name": "Test Restaurant",
        "subdomain": "test",
    }


def test_chat_requires_authentication():
    response = client.post(
        "/api/chats/orders",
        json=_chat_payload(),
    )

    assert response.status_code == 401


@patch("src.api.routes.chats.chatbot_agent")
def test_authenticated_chat_passes_user_id_into_graph(
    mock_agent,
):
    _, token = signup_and_login()

    mock_agent.stream.return_value = iter(
        [
            {
                "messages": [
                    AIMessage(content="Hello from the agent.")
                ]
            }
        ]
    )

    response = client.post(
        "/api/chats/orders",
        json=_chat_payload(
            session_id=f"session-{uuid4().hex}"
        ),
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    assert "Hello from the agent." in response.text

    call = mock_agent.stream.call_args

    assert call is not None

    state = call.args[0]
    graph_config = call.args[1]

    assert isinstance(state["user_id"], int)
    assert state["user_id"] > 0

    thread_id = graph_config["configurable"]["thread_id"]

    assert thread_id.startswith(
        f"user:{state['user_id']}:session:"
    )


@patch("src.api.routes.chats.chatbot_agent")
def test_same_session_id_isolated_between_users(
    mock_agent,
):
    _, token_a = signup_and_login()
    _, token_b = signup_and_login()

    mock_agent.stream.return_value = iter(
        [
            {
                "messages": [
                    AIMessage(content="ok")
                ]
            }
        ]
    )

    session_id = "shared-client-session"

    response_a = client.post(
        "/api/chats/orders",
        json=_chat_payload(session_id),
        headers=auth_headers(token_a),
    )

    assert response_a.status_code == 200

    config_a = mock_agent.stream.call_args.args[1]
    thread_a = config_a["configurable"]["thread_id"]

    response_b = client.post(
        "/api/chats/orders",
        json=_chat_payload(session_id),
        headers=auth_headers(token_b),
    )

    assert response_b.status_code == 200

    config_b = mock_agent.stream.call_args.args[1]
    thread_b = config_b["configurable"]["thread_id"]

    assert thread_a != thread_b
    assert thread_a.startswith("user:")
    assert thread_b.startswith("user:")


@patch("src.api.routes.chats.chatbot_agent")
def test_authenticated_chat_uses_original_session_id_inside_namespace(
    mock_agent,
):
    _, token = signup_and_login()

    mock_agent.stream.return_value = iter(
        [
            {
                "messages": [
                    AIMessage(content="ok")
                ]
            }
        ]
    )

    session_id = "conversation-123"

    response = client.post(
        "/api/chats/orders",
        json=_chat_payload(session_id),
        headers=auth_headers(token),
    )

    assert response.status_code == 200

    thread_id = mock_agent.stream.call_args.args[1][
        "configurable"
    ]["thread_id"]

    assert thread_id.endswith(
        f":session:{session_id}"
    )
