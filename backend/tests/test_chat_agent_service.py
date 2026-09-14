"""AI application service regression tests."""

from unittest.mock import Mock

from src.services.chat_agent import ChatAgentService


def test_chat_agent_service_exposes_graph_state():
    service = ChatAgentService.__new__(ChatAgentService)

    service.agent = Mock()

    expected = {"messages": [], "cart": {"items": []}}

    service.agent.get_state.return_value = expected

    result = service.get_state({"configurable": {"thread_id": "test"}})

    assert result == expected
    service.agent.get_state.assert_called_once_with(
        {"configurable": {"thread_id": "test"}}
    )


def test_chat_agent_service_updates_graph_state():
    service = ChatAgentService.__new__(ChatAgentService)

    service.agent = Mock()

    service.update_state(
        {"configurable": {"thread_id": "test"}},
        {"cart": {"items": []}},
    )

    service.agent.update_state.assert_called_once_with(
        {"configurable": {"thread_id": "test"}},
        {"cart": {"items": []}},
    )


def test_chat_agent_service_streams_done_event():
    service = ChatAgentService.__new__(ChatAgentService)

    message = Mock()
    message.__class__.__name__ = "AIMessage"
    message.content = "Hello"
    message.tool_calls = []

    service.agent = Mock()
    service.agent.stream.return_value = [
        {"messages": [message]},
    ]

    events = list(
        service.stream_response(
            user_message="hello",
            restaurant_name="Test Restaurant",
            subdomain="test",
            user_id=1,
            graph_config={
                "configurable": {
                    "thread_id": "test",
                }
            },
        )
    )

    assert len(events) == 2
    assert '"type": "AIMessage"' in events[0]
    assert '"content": "Hello"' in events[0]
    assert events[1] == "data: [DONE]\n\n"


def test_chat_agent_service_converts_agent_errors_to_sse():
    service = ChatAgentService.__new__(ChatAgentService)

    service.agent = Mock()
    service.agent.stream.side_effect = RuntimeError("boom")

    events = list(
        service.stream_response(
            user_message="hello",
            restaurant_name="Test Restaurant",
            subdomain="test",
            user_id=1,
            graph_config={
                "configurable": {
                    "thread_id": "test",
                }
            },
        )
    )

    assert len(events) == 2
    assert '"type": "error"' in events[0]
    assert "unexpected error" in events[0]
    assert events[1] == "data: [DONE]\n\n"
