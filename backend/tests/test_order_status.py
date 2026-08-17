from unittest.mock import Mock, patch

import requests
from langchain_core.messages import ToolMessage

from src.agents.nodes.tool_node import tools
from src.agents.tools.order import get_order_status
from tests.test_cart_tools import make_cart, make_state, run_tool


def order_response(status_code=200, payload=None):
    result = Mock()
    result.status_code = status_code
    result.json.return_value = payload if payload is not None else {
        "order_id": "ORD-123", "restaurant_name": "Test Restaurant", "subdomain": "test",
        "items": [{"item_id": "item-001", "title": "Chicken Biryani", "quantity": 2,
                   "base_price": 220.0, "variation": None}],
        "subtotal": 440.0, "status": "confirmed",
    }
    result.raise_for_status.side_effect = (
        requests.HTTPError(f"{status_code} error") if status_code >= 400 else None
    )
    return result


def lookup(state, args=None):
    return run_tool(state, "get_order_status", args or {}, "test-order-status")


def tool_content(result):
    message = result["messages"][-1]
    assert isinstance(message, ToolMessage)
    return message.content


def assert_state_unchanged(before, after):
    assert after["cart"] == before["cart"]
    assert after["orderId"] == before["orderId"]
    assert after["finished"] == before["finished"]


def test_tool_is_registered_and_explicit_order_id_succeeds():
    assert get_order_status in tools
    state = make_state(make_cart())
    before = state.copy()
    with patch("src.agents.tools.order.requests.get", return_value=order_response()) as get:
        result = lookup(state, {"order_id": "ORD-EXPLICIT"})
    assert get.call_args.args[0].endswith("/orders/ORD-EXPLICIT")
    assert "Order ORD-123 is confirmed." in tool_content(result)
    assert_state_unchanged(before, result)


def test_state_order_id_succeeds_and_formats_response():
    state = make_state(make_cart())
    state["orderId"] = "ORD-STATE"
    before = state.copy()
    with patch("src.agents.tools.order.requests.get", return_value=order_response()):
        result = lookup(state)
    content = tool_content(result)
    assert "Restaurant: Test Restaurant" in content
    assert "- Chicken Biryani × 2 — ₹440" in content
    assert "Total: ₹440" in content
    assert "Status: confirmed" in content
    assert_state_unchanged(before, result)


def test_no_order_id_does_not_call_backend_or_change_state():
    state = make_state(make_cart())
    before = state.copy()
    with patch("src.agents.tools.order.requests.get") as get:
        result = lookup(state)
    get.assert_not_called()
    assert "no active or recent order" in tool_content(result)
    assert_state_unchanged(before, result)


def test_not_found_and_http_errors_are_safe():
    for status_code in (404, 400, 500):
        state = make_state(make_cart())
        state["orderId"] = "ORD-123"
        before = state.copy()
        with patch("src.agents.tools.order.requests.get", return_value=order_response(status_code)):
            result = lookup(state)
        assert "Unable to check order status" in tool_content(result) or "was not found" in tool_content(result)
        assert_state_unchanged(before, result)


def test_connection_failure_and_timeout_are_safe():
    for error in (requests.ConnectionError, requests.Timeout):
        state = make_state(make_cart())
        state["orderId"] = "ORD-123"
        before = state.copy()
        with patch("src.agents.tools.order.requests.get", side_effect=error):
            result = lookup(state)
        assert "Unable to check order status" in tool_content(result)
        assert_state_unchanged(before, result)


def test_malformed_response_and_missing_order_id_are_safe():
    malformed_payloads = [[], {"restaurant_name": "Test Restaurant"}]
    for payload in malformed_payloads:
        state = make_state(make_cart())
        state["orderId"] = "ORD-123"
        before = state.copy()
        with patch("src.agents.tools.order.requests.get", return_value=order_response(payload=payload)):
            result = lookup(state)
        assert "invalid response" in tool_content(result)
        assert_state_unchanged(before, result)
