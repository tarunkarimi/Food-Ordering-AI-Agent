import json
import logging

from src.agents.nodes import chatbot as chatbot_module
from src.agents.nodes import tool_node as tool_node_module
from src.agents.state import Cart
from src.observability.logging import set_request_id


def test_chatbot_logs_agent_invocation_metadata(
    monkeypatch,
    caplog,
):
    class FakeModel:
        def invoke(self, messages):
            from langchain_core.messages import AIMessage

            return AIMessage(
                content="test response",
                tool_calls=[],
            )

    monkeypatch.setattr(
        chatbot_module,
        "_model_with_tools",
        FakeModel(),
    )

    monkeypatch.setattr(
        chatbot_module,
        "_persist_cart",
        lambda state, cart: None,
    )

    set_request_id("agent-test-001")

    state = {
        "messages": [
            {
                "role": "user",
                "content": "hello",
            },
        ],
        "cart": Cart(items=[]),
        "restaurant_name": "Test Restaurant",
        "subdomain": "test",
        "user_id": 42,
        "finished": False,
    }

    with caplog.at_level(
        logging.INFO,
        logger="src.agents.nodes.chatbot",
    ):
        chatbot_module.chatbot(state)

    events = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "src.agents.nodes.chatbot"
    ]

    assert any(
        event["event"] == "agent_invocation_started"
        for event in events
    )

    completed = next(
        event
        for event in events
        if event["event"] == "agent_invocation_completed"
    )

    assert completed["request_id"] == "agent-test-001"
    assert completed["tool_call_count"] == 0
    assert completed["duration_ms"] >= 0


def test_tool_node_logs_tool_metadata(
    monkeypatch,
    caplog,
):
    class FakeToolNode:
        def invoke(self, state, config=None):
            return {
                "messages": [],
            }

    monkeypatch.setattr(
        tool_node_module,
        "_single_tool_node",
        FakeToolNode(),
    )

    set_request_id("tool-test-001")

    from langchain_core.messages import AIMessage

    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_menu",
                        "args": {},
                        "id": "tool-call-1",
                        "type": "tool_call",
                    },
                ],
            ),
        ],
        "user_id": 42,
        "cart": Cart(items=[]),
    }

    with caplog.at_level(
        logging.INFO,
        logger="src.agents.nodes.tool_node",
    ):
        tool_node_module.tool_node(state)

    events = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "src.agents.nodes.tool_node"
    ]

    completed = next(
        event
        for event in events
        if event["event"] == "agent_tool_completed"
    )

    assert completed["request_id"] == "tool-test-001"
    assert completed["tool_name"] == "get_menu"
    assert completed["duration_ms"] >= 0


def test_tool_logging_does_not_include_tool_arguments(
    monkeypatch,
    caplog,
):
    class FakeToolNode:
        def invoke(self, state, config=None):
            return {
                "messages": [],
            }

    monkeypatch.setattr(
        tool_node_module,
        "_single_tool_node",
        FakeToolNode(),
    )

    set_request_id("privacy-test-001")

    from langchain_core.messages import AIMessage

    secret_value = "PRIVATE-USER-DATA-123"

    state = {
        "messages": [
            AIMessage(
                content=secret_value,
                tool_calls=[
                    {
                        "name": "get_menu",
                        "args": {
                            "secret": secret_value,
                        },
                        "id": "tool-call-2",
                        "type": "tool_call",
                    },
                ],
            ),
        ],
        "user_id": 42,
        "cart": Cart(items=[]),
    }

    with caplog.at_level(
        logging.INFO,
        logger="src.agents.nodes.tool_node",
    ):
        tool_node_module.tool_node(state)

    output = "\n".join(
        record.message
        for record in caplog.records
    )

    assert secret_value not in output
    assert '"args"' not in output
