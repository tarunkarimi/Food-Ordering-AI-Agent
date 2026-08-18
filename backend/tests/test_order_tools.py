from unittest.mock import Mock, patch

import requests

from tests.test_cart_tools import make_cart, make_state, run_tool


def place(state):
    return run_tool(state, "place_order", {}, "test-place-order")


def response(status_code=201, payload=None):
    result = Mock()
    result.status_code = status_code
    result.json.return_value = payload or {"order_id": "ORD-123", "subtotal": 440.0}
    result.raise_for_status.side_effect = (
        requests.HTTPError(f"{status_code} error") if status_code >= 400 else None
    )
    return result


def test_empty_cart_cannot_place_order():
    state = make_state(make_cart())
    state["cart"].items = []
    with patch("src.agents.tools.cart.requests.post") as post:
        result = place(state)
    post.assert_not_called()
    assert result["cart"].items == []
    assert result["orderId"] is None
    assert result["finished"] is False


def test_successful_order_placement_clears_cart_and_sets_completion():
    state = make_state(make_cart())
    with patch("src.agents.tools.cart.requests.post", return_value=response()) as post:
        result = place(state)
    post.assert_called_once()
    assert result["cart"].items == []
    assert result["orderId"] == "ORD-123"
    assert result["order_status"] == "confirmed"
    assert result["finished"] is True


def test_backend_errors_preserve_order_state():
    for status_code in (400, 500):
        state = make_state(make_cart())
        with patch("src.agents.tools.cart.requests.post", return_value=response(status_code)):
            result = place(state)
        assert len(result["cart"].items) == 1
        assert result["orderId"] is None
        assert result["finished"] is False


def test_connection_failure_preserves_order_state():
    state = make_state(make_cart())
    with patch("src.agents.tools.cart.requests.post", side_effect=requests.ConnectionError):
        result = place(state)
    assert len(result["cart"].items) == 1
    assert result["orderId"] is None
    assert result["finished"] is False


def test_timeout_preserves_order_state():
    state = make_state(make_cart())
    with patch("src.agents.tools.cart.requests.post", side_effect=requests.Timeout):
        result = place(state)
    assert len(result["cart"].items) == 1
    assert result["orderId"] is None
    assert result["finished"] is False


def test_missing_order_id_preserves_order_state():
    state = make_state(make_cart())
    with patch("src.agents.tools.cart.requests.post", return_value=response(payload={"subtotal": 440.0})):
        result = place(state)
    assert len(result["cart"].items) == 1
    assert result["orderId"] is None
    assert result["finished"] is False
