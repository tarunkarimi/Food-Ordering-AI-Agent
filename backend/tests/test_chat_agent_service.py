"""AI application service regression tests."""

from unittest.mock import Mock

import requests
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

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
    streamed_state = service.agent.stream.call_args.args[0]
    assert streamed_state["subdomain"] == "test"
    assert "order_confirmation_pending" not in streamed_state


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


def test_old_persisted_order_does_not_authorize_new_success_claim():
    class StaleOrderAgent:
        def stream(self, *_args, **_kwargs):
            yield {
                "messages": [
                    HumanMessage(content="What happened with my order?"),
                    AIMessage(content="Your order was successfully placed."),
                ],
                "orderId": "OLD-DURABLE-ORDER",
                "order_status": "confirmed",
                "order_history_persisted": True,
            }

    service = ChatAgentService(agent=StaleOrderAgent())
    events = list(
        service.stream_response(
            user_message="What happened with my order?",
            restaurant_name="Test Restaurant",
            subdomain="test",
            user_id=77,
            graph_config={"configurable": {"thread_id": "user:77:session:stale-order"}},
        )
    )

    assert "OLD-DURABLE-ORDER" not in "".join(events)
    assert "Reply yes to confirm" in "".join(events)


def test_chat_confirmation_survives_turns_and_retries_checkout_safely(monkeypatch):
    from src.agents.graph import chatbot_agent_builder
    from src.agents.nodes import chatbot as chatbot_node
    from src.agents.state import Cart, CartItem, CartItemUnit, ItemVariation

    cart = Cart(
        items=[
            CartItem(
                item_id="chicken-65",
                title="Chicken 65",
                units=[
                    CartItemUnit(
                        key="chicken-65|regular",
                        quantity=1,
                        base_price=200.0,
                        variation=ItemVariation(
                            id="regular",
                            name="Regular",
                            price="200",
                        ),
                    )
                ],
            )
        ]
    )
    tool_call_counter = 0

    class DeterministicCheckoutModel:
        def invoke(self, messages):
            nonlocal tool_call_counter
            last_human = next(
                message
                for message in reversed(messages)
                if isinstance(message, HumanMessage)
            )
            latest = messages[-1]
            if isinstance(latest, ToolMessage):
                # Deliberately try to hallucinate success after a failed tool.
                return AIMessage(content="Your order has been placed successfully.")

            tool_name = "confirm_order" if last_human.content == "confirm order" else "place_order"
            tool_call_counter += 1
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": tool_name,
                        "args": {},
                        "id": f"synthetic-{tool_name}-{tool_call_counter}",
                        "type": "tool_call",
                    }
                ],
            )

    order_attempts = []

    def create_order_with_retry(*, payload, idempotency_key, order_url):
        order_attempts.append(
            {
                "payload": payload,
                "idempotency_key": idempotency_key,
                "order_url": order_url,
            }
        )
        if len(order_attempts) == 1:
            raise requests.Timeout("synthetic timeout")
        return (
            {
                "order_id": "ORD-SYNTHETIC-CHAT-001",
                "status": "confirmed",
                "subtotal": 200.0,
            },
            1,
        )

    monkeypatch.setattr(chatbot_node, "_model_with_tools", DeterministicCheckoutModel())
    monkeypatch.setattr(chatbot_node, "_load_persistent_cart", lambda _state: cart)
    monkeypatch.setattr(chatbot_node, "_persist_cart", lambda *_args: None)
    monkeypatch.setattr(chatbot_node, "_load_persistent_ordering_context", lambda _state: {})
    monkeypatch.setattr(chatbot_node, "_capture_persistent_ai_memory", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(chatbot_node, "build_ai_memory_context", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        "src.agents.tools.cart._place_order_with_outbox",
        create_order_with_retry,
    )

    service = ChatAgentService(agent=chatbot_agent_builder())
    graph_config = {"configurable": {"thread_id": "user:77:session:checkout-flow"}}

    summary_events = list(
        service.stream_response(
            user_message="confirm order",
            restaurant_name="Test Restaurant",
            subdomain="test",
            user_id=77,
            graph_config=graph_config,
        )
    )
    assert any('"type": "AIMessage"' in event and "confirm" in event.lower() for event in summary_events), summary_events
    assert order_attempts == []

    failed_events = list(
        service.stream_response(
            user_message="yes",
            restaurant_name="Test Restaurant",
            subdomain="test",
            user_id=77,
            graph_config=graph_config,
        )
    )
    failed_text = "".join(failed_events).lower()
    assert "timed out before confirming" in failed_text
    assert "your cart is still saved" in failed_text
    assert "your order has been placed successfully" not in failed_text
    assert len(order_attempts) == 1

    success_events = list(
        service.stream_response(
            user_message="yes",
            restaurant_name="Test Restaurant",
            subdomain="test",
            user_id=77,
            graph_config=graph_config,
        )
    )
    success_text = "".join(success_events)
    assert "ORD-SYNTHETIC-CHAT-001 is confirmed and saved in My Orders" in success_text
    assert "Your order has been placed successfully" not in success_text
    assert len(order_attempts) == 2
    assert order_attempts[0]["idempotency_key"] == order_attempts[1]["idempotency_key"]
    assert order_attempts[0]["payload"] == order_attempts[1]["payload"]
    assert order_attempts[0]["payload"] == {
        "restaurant_name": "Test Restaurant",
        "subdomain": "test",
        "user_id": "77",
        "items": [
            {
                "item_id": "chicken-65",
                "title": "Chicken 65",
                "quantity": 1,
                "base_price": 200.0,
                "variation": {"id": "regular", "name": "Regular", "price": "200"},
            }
        ],
    }
