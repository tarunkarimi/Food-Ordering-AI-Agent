from langchain_core.messages import AIMessage
from langgraph.types import Command

from src.agents.nodes.tool_node import _apply_result
from tests.test_cart_tools import make_cart, make_state


def test_apply_result_propagates_command_state_fields_and_messages():
    state = make_state(make_cart())
    message = object()
    updated_cart = make_cart(3)

    result = Command(
        update={
            "cart": updated_cart,
            "orderId": "ORD-123",
            "order_status": "confirmed",
            "order_confirmation_pending": False,
            "finished": True,
            "messages": [message],
        }
    )

    messages = _apply_result(state, result)

    assert state["cart"] == updated_cart
    assert state["orderId"] == "ORD-123"
    assert state["order_status"] == "confirmed"
    assert state["order_confirmation_pending"] is False
    assert state["finished"] is True
    assert messages == [message]


def test_apply_result_propagates_dict_state_fields_and_messages():
    state = make_state(make_cart())
    message = object()
    updated_cart = make_cart(4)

    result = {
        "cart": updated_cart,
        "orderId": "ORD-456",
        "order_status": "cancelled",
        "order_confirmation_pending": False,
        "finished": True,
        "messages": [message],
    }

    messages = _apply_result(state, result)

    assert state["cart"] == updated_cart
    assert state["orderId"] == "ORD-456"
    assert state["order_status"] == "cancelled"
    assert state["order_confirmation_pending"] is False
    assert state["finished"] is True
    assert messages == [message]


def test_apply_result_recursively_handles_list_results():
    state = make_state(make_cart())
    first_message = object()
    second_message = object()

    result = [
        {
            "orderId": "ORD-FIRST",
            "messages": [first_message],
        },
        Command(
            update={
                "order_status": "confirmed",
                "finished": True,
                "messages": [second_message],
            }
        ),
    ]

    messages = _apply_result(state, result)

    assert state["orderId"] == "ORD-FIRST"
    assert state["order_status"] == "confirmed"
    assert state["finished"] is True
    assert messages == [
        first_message,
        second_message,
    ]


def test_apply_result_ignores_unrecognized_result_types():
    state = make_state(make_cart())
    before = dict(state)

    messages = _apply_result(
        state,
        AIMessage(content="not a tool result"),
    )

    assert messages == []
    assert state == before