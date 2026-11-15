from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage
from datetime import datetime, timezone
from types import SimpleNamespace
import pytest

from src.agents.nodes.chatbot import (
    _load_persistent_ordering_context,
    chatbot,
)
from src.services import persistent_ordering_intelligence as persistent_service


def _state(user_id, message="Recommend something for me."):
    return {
        "messages": [
            HumanMessage(content=message),
        ],
        "cart": None,
        "orderId": None,
        "order_status": None,
        "order_confirmation_pending": False,
        "restaurant_name": "Test Restaurant",
        "subdomain": "test",
        "user_id": user_id,
        "finished": False,
    }


def test_authenticated_user_loads_persistent_ordering_context():
    state = _state(123)

    expected = {
        "ordering_history": {
            "total_orders": 8,
            "total_items": 19,
            "total_spend": 4200.0,
            "average_order_value": 525.0,
            "last_order_id": "ORDER-8",
            "last_order_at": "2026-09-15T19:00:00",
            "weekday_patterns": {
                "saturday": 4,
                "sunday": 3,
                "monday": 1,
            },
            "meal_period_patterns": {
                "dinner": 6,
                "lunch": 2,
            },
            "favorite_items": [
                {
                    "item_key": "biryani-1",
                    "item_title": "Chicken Biryani",
                    "restaurant_name": "Test Restaurant",
                    "order_count": 6,
                    "total_quantity": 9,
                }
            ],
            "favorite_restaurants": [
                {
                    "restaurant_name": "Test Restaurant",
                    "order_count": 8,
                    "total_spend": 4200.0,
                }
            ],
        }
    }

    with patch(
        "src.agents.nodes.chatbot.SessionLocal"
    ) as session_local, patch(
        "src.agents.nodes.chatbot.build_persistent_ai_ordering_context",
        return_value=expected,
    ) as build_context:
        result = _load_persistent_ordering_context(state)

    assert result == expected
    build_context.assert_called_once()

    args, kwargs = build_context.call_args

    assert kwargs["user_id"] == 123
    assert kwargs["restaurant_name"] == "Test Restaurant"
    assert kwargs["subdomain"] == "test"

    session_local.return_value.__enter__.assert_called_once()


def test_anonymous_user_does_not_load_persistent_ordering_context():
    state = _state(None)

    with patch(
        "src.agents.nodes.chatbot.build_persistent_ai_ordering_context"
    ) as build_context:
        result = _load_persistent_ordering_context(state)

    assert result == {}
    build_context.assert_not_called()


def test_same_display_name_context_uses_only_requested_subdomain(monkeypatch):
    tenant_a = SimpleNamespace(
        user_id=123, subdomain="tenant-a", restaurant_name="Shared Kitchen",
        status="confirmed", order_id="A-1", subtotal=100,
        created_at=datetime(2026, 10, 2, 18, tzinfo=timezone.utc),
        items_json='[{"item_id":"same-id","title":"Shared Dish","quantity":2}]',
    )
    tenant_b = SimpleNamespace(
        user_id=123, subdomain="tenant-b", restaurant_name="Shared Kitchen",
        status="confirmed", order_id="B-1", subtotal=900,
        created_at=datetime(2026, 10, 3, 18, tzinfo=timezone.utc),
        items_json='[{"item_id":"same-id","title":"Shared Dish","quantity":9}]',
    )
    observed = []

    def load_orders(db, *, user_id, subdomain, restaurant_name):
        observed.append((user_id, subdomain, restaurant_name))
        return [tenant_a] if subdomain == "tenant-a" else [tenant_b]

    monkeypatch.setattr(persistent_service, "_load_tenant_order_history", load_orders)
    context = persistent_service.build_persistent_ai_ordering_context(
        object(), user_id=123, restaurant_name="Shared Kitchen", subdomain="tenant-a"
    )
    assert observed == [(123, "tenant-a", "Shared Kitchen")]
    assert context["ordering_history"]["total_orders"] == 1
    assert context["ordering_history"]["total_spend"] == 100.0
    assert context["favorite_items"][0]["total_quantity"] == 2


def test_missing_tenant_does_not_load_ambiguous_aggregate(monkeypatch):
    monkeypatch.setattr(
        persistent_service,
        "_resolve_unique_ordering_subdomain",
        lambda db, user_id: None,
    )
    monkeypatch.setattr(
        persistent_service,
        "_load_tenant_order_history",
        lambda *args, **kwargs: pytest.fail("ambiguous tenant history was loaded"),
    )
    context = persistent_service.build_persistent_ai_ordering_context(
        object(), user_id=123, restaurant_name="Shared Kitchen"
    )
    assert context["ordering_history"]["total_orders"] == 0
    assert context["favorite_items"] == []


def test_missing_tenant_resolves_single_tenant_for_legacy_single_tenant_users(
    monkeypatch,
):
    observed = []
    monkeypatch.setattr(
        persistent_service,
        "_resolve_unique_ordering_subdomain",
        lambda db, user_id: "tenant-a",
    )
    monkeypatch.setattr(
        persistent_service,
        "_load_tenant_order_history",
        lambda db, **kwargs: observed.append(kwargs) or [],
    )
    persistent_service.build_persistent_ai_ordering_context(
        object(), user_id=123, restaurant_name="Shared Kitchen"
    )
    assert observed == [{
        "user_id": 123,
        "subdomain": "tenant-a",
        "restaurant_name": "Shared Kitchen",
    }]


def test_tenant_order_history_query_filters_before_aggregation():
    class Result:
        def all(self):
            return []

    class QueryOnlySession:
        statement = None

        def scalars(self, statement):
            self.statement = statement
            return Result()

    db = QueryOnlySession()
    assert persistent_service._load_tenant_order_history(
        db,
        user_id=123,
        subdomain="tenant-a",
        restaurant_name="Shared Kitchen",
    ) == []
    params = db.statement.compile().params.values()
    assert 123 in params
    assert "tenant-a" in params
    assert "Shared Kitchen" in params


def test_chatbot_injects_persistent_context_into_model():
    state = _state(456)

    persistent_context = {
        "ordering_history": {
            "total_orders": 5,
            "total_items": 12,
            "total_spend": 2500.0,
            "average_order_value": 500.0,
            "last_order_id": "ORDER-5",
            "last_order_at": "2026-09-15T20:00:00",
            "weekday_patterns": {
                "saturday": 3,
                "monday": 2,
            },
            "meal_period_patterns": {
                "dinner": 4,
                "lunch": 1,
            },
            "favorite_items": [
                {
                    "item_key": "biryani-1",
                    "item_title": "Chicken Biryani",
                    "restaurant_name": "Test Restaurant",
                    "order_count": 4,
                    "total_quantity": 7,
                }
            ],
            "favorite_restaurants": [
                {
                    "restaurant_name": "Test Restaurant",
                    "order_count": 5,
                    "total_spend": 2500.0,
                }
            ],
        }
    }

    model_response = AIMessage(
        content="Based on your previous orders, Chicken Biryani looks like a good choice."
    )

    captured_messages = []

    class FakeModel:
        def invoke(self, messages):
            captured_messages.extend(messages)
            return model_response

    with patch(
        "src.agents.nodes.chatbot._model_with_tools",
        new=FakeModel(),
    ), patch(
        "src.agents.nodes.chatbot._load_persistent_cart",
        return_value={"items": []},
    ), patch(
        "src.agents.nodes.chatbot._load_persistent_ordering_context",
        return_value=persistent_context,
    ), patch(
        "src.agents.nodes.chatbot._persist_cart",
    ), patch(
        "src.agents.nodes.chatbot._capture_persistent_ai_memory",
    ), patch(
        "src.agents.nodes.chatbot.build_ai_memory_context",
        return_value={},
    ), patch(
        "src.agents.nodes.chatbot.SessionLocal",
    ):
        result = chatbot(state)

    assert result["messages"][-1].content == model_response.content

    assert len(captured_messages) == 3

    context_message = captured_messages[1]

    assert context_message[0] == "system"
    assert "PERSISTENT ORDERING CONTEXT" in context_message[1]
    assert "Chicken Biryani" in context_message[1]
    assert "Test Restaurant" in context_message[1]
    assert "total_orders" in context_message[1]
    assert "Current menu data remains authoritative" in context_message[1]

    customer_message = captured_messages[2]

    assert customer_message.content == "Recommend something for me."


def test_chatbot_without_persistent_context_preserves_normal_message_flow():
    state = _state(789)

    model_response = AIMessage(
        content="Here are some options from the menu."
    )

    captured_messages = []

    class FakeModel:
        def invoke(self, messages):
            captured_messages.extend(messages)
            return model_response

    with patch(
        "src.agents.nodes.chatbot._model_with_tools",
        new=FakeModel(),
    ), patch(
        "src.agents.nodes.chatbot._load_persistent_cart",
        return_value={"items": []},
    ), patch(
        "src.agents.nodes.chatbot._load_persistent_ordering_context",
        return_value={},
    ), patch(
        "src.agents.nodes.chatbot._persist_cart",
    ), patch(
        "src.agents.nodes.chatbot._capture_persistent_ai_memory",
    ), patch(
        "src.agents.nodes.chatbot.build_ai_memory_context",
        return_value={},
    ), patch(
        "src.agents.nodes.chatbot.SessionLocal",
    ):
        result = chatbot(state)

    assert result["messages"][-1].content == model_response.content
    assert len(captured_messages) == 2
    assert captured_messages[0][0] == "system"
    assert captured_messages[1].content == "Recommend something for me."


def test_missing_tenant_keeps_user_level_ai_memory_available():
    state = _state(999)
    state["subdomain"] = ""
    captured_messages = []

    class FakeModel:
        def invoke(self, messages):
            captured_messages.extend(messages)
            return AIMessage(content="I remember your food preference.")

    with patch("src.agents.nodes.chatbot._model_with_tools", new=FakeModel()), \
        patch("src.agents.nodes.chatbot._load_persistent_cart", return_value={"items": []}), \
        patch("src.agents.nodes.chatbot._load_persistent_ordering_context", return_value={}), \
        patch("src.agents.nodes.chatbot.build_ai_memory_context", return_value={
            "explicit_preferences": [{"memory_value": "spicy food", "polarity": "like"}],
        }), \
        patch("src.agents.nodes.chatbot.SessionLocal"), \
        patch("src.agents.nodes.chatbot._persist_cart"):
        chatbot(state)

    assert any(
        isinstance(message, tuple)
        and message[0] == "system"
        and "EXPLICIT CUSTOMER MEMORY" in message[1]
        and "spicy food" in message[1]
        for message in captured_messages
    )
