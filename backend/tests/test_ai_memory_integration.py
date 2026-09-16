"""Phase 16 AI memory integration tests."""

from unittest.mock import Mock

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from src.agents.nodes import chatbot as chatbot_module
from src.agents.nodes.chatbot import chatbot
from src.db.database import SessionLocal
from src.main import app
from src.services.ai_memory import (
    build_ai_memory_context,
    capture_user_message_memories,
)

from tests.test_ai_memory import signup_and_login


def _chat_state(user_id=None):
    return {
        "messages": [HumanMessage(content="What should I order?")],
        "cart": [],
        "restaurant_name": "Test Restaurant",
        "subdomain": "test-restaurant",
        "user_id": user_id,
        "finished": False,
    }


def _fake_model(captured_messages):
    model = Mock()

    def fake_invoke(messages):
        captured_messages.extend(messages)
        return AIMessage(content="Here are some options.")

    model.invoke.side_effect = fake_invoke
    return model


def test_authenticated_memory_is_injected_into_chatbot(monkeypatch):
    user_id, _ = signup_and_login()

    with SessionLocal() as db:
        capture_user_message_memories(
            db,
            user_id=user_id,
            user_message="I prefer spicy food.",
        )
        db.commit()

    captured_messages = []

    monkeypatch.setattr(
        chatbot_module,
        "_model_with_tools",
        _fake_model(captured_messages),
    )
    monkeypatch.setattr(
        chatbot_module,
        "_load_persistent_ordering_context",
        lambda state: {},
    )
    monkeypatch.setattr(
        chatbot_module,
        "_persist_cart",
        lambda state, cart: None,
    )

    result = chatbot(_chat_state(user_id))

    assert result["messages"][-1].content == "Here are some options."

    memory_messages = [
        message
        for message in captured_messages
        if isinstance(message, tuple)
        and message[0] == "system"
        and "EXPLICIT CUSTOMER MEMORY" in message[1]
    ]

    assert len(memory_messages) == 1
    assert "spicy" in memory_messages[0][1].lower()
    assert "historical preference data" in memory_messages[0][1].lower()
    assert "newer explicit customer request always takes precedence" in (
        memory_messages[0][1].lower()
    )


def test_anonymous_chatbot_does_not_receive_persistent_ai_memory(monkeypatch):
    captured_messages = []

    monkeypatch.setattr(
        chatbot_module,
        "_model_with_tools",
        _fake_model(captured_messages),
    )
    monkeypatch.setattr(
        chatbot_module,
        "_load_persistent_ordering_context",
        lambda state: {},
    )
    monkeypatch.setattr(
        chatbot_module,
        "_persist_cart",
        lambda state, cart: None,
    )

    chatbot(_chat_state())

    memory_messages = [
        message
        for message in captured_messages
        if isinstance(message, tuple)
        and message[0] == "system"
        and "EXPLICIT CUSTOMER MEMORY" in message[1]
    ]

    assert memory_messages == []


def test_current_user_message_remains_after_historical_memory(monkeypatch):
    user_id, _ = signup_and_login()

    with SessionLocal() as db:
        capture_user_message_memories(
            db,
            user_id=user_id,
            user_message="I prefer spicy food.",
        )
        db.commit()

    captured_messages = []

    monkeypatch.setattr(
        chatbot_module,
        "_model_with_tools",
        _fake_model(captured_messages),
    )
    monkeypatch.setattr(
        chatbot_module,
        "_load_persistent_ordering_context",
        lambda state: {},
    )
    monkeypatch.setattr(
        chatbot_module,
        "_persist_cart",
        lambda state, cart: None,
    )

    state = _chat_state(user_id)
    state["messages"] = [
        HumanMessage(content="Actually, I want something mild today.")
    ]

    chatbot(state)

    memory_index = next(
        index
        for index, message in enumerate(captured_messages)
        if isinstance(message, tuple)
        and message[0] == "system"
        and "EXPLICIT CUSTOMER MEMORY" in message[1]
    )

    current_message_index = next(
        index
        for index, message in enumerate(captured_messages)
        if isinstance(message, HumanMessage)
        and message.content == "Actually, I want something mild today."
    )

    assert memory_index < current_message_index


def test_memory_loading_failure_does_not_break_chatbot(monkeypatch):
    user_id, _ = signup_and_login()

    def failing_session(*args, **kwargs):
        raise RuntimeError("simulated memory database failure")

    monkeypatch.setattr(
        chatbot_module,
        "SessionLocal",
        failing_session,
    )
    monkeypatch.setattr(
        chatbot_module,
        "_load_persistent_ordering_context",
        lambda state: {},
    )
    monkeypatch.setattr(
        chatbot_module,
        "_persist_cart",
        lambda state, cart: None,
    )

    fake_model = Mock()
    fake_model.invoke.return_value = AIMessage(
        content="Chat continues normally."
    )

    monkeypatch.setattr(
        chatbot_module,
        "_model_with_tools",
        fake_model,
    )

    result = chatbot(_chat_state(user_id))

    assert result["messages"][-1].content == "Chat continues normally."


def _authenticated_client(token):
    client = TestClient(app)
    client.headers.update(
        {"Authorization": f"Bearer {token}"}
    )
    return client


def test_ai_memory_api_is_user_scoped():
    user_one, token_one = signup_and_login()
    user_two, token_two = signup_and_login()

    with SessionLocal() as db:
        capture_user_message_memories(
            db,
            user_id=user_one,
            user_message="I prefer Andhra food.",
        )
        capture_user_message_memories(
            db,
            user_id=user_two,
            user_message="I prefer North Indian food.",
        )
        db.commit()

    client_one = _authenticated_client(token_one)
    client_two = _authenticated_client(token_two)

    response_one = client_one.get("/api/ai-memory")
    response_two = client_two.get("/api/ai-memory")

    assert response_one.status_code == 200
    assert response_two.status_code == 200

    values_one = {
        memory.get("memory_value", memory.get("value"))
        for memory in response_one.json()["memories"]
    }
    values_two = {
        memory.get("memory_value", memory.get("value"))
        for memory in response_two.json()["memories"]
    }

    assert "andhra food" in values_one
    assert "north indian food" in values_two
    assert "north indian food" not in values_one
    assert "andhra food" not in values_two


def test_ai_memory_api_can_delete_memory():
    user_id, token = signup_and_login()
    client = _authenticated_client(token)

    with SessionLocal() as db:
        capture_user_message_memories(
            db,
            user_id=user_id,
            user_message="I prefer Andhra food.",
        )
        db.commit()

        context = build_ai_memory_context(
            db,
            user_id=user_id,
        )

        assert len(context["explicit_preferences"]) == 1

    response = client.get("/api/ai-memory")

    assert response.status_code == 200

    memories = response.json()["memories"]

    assert len(memories) == 1

    memory_id = memories[0]["id"]

    delete_response = client.delete(
        f"/api/ai-memory/{memory_id}"
    )

    assert delete_response.status_code == 200

    after_delete = client.get("/api/ai-memory")

    assert after_delete.status_code == 200
    assert after_delete.json()["memories"] == []

