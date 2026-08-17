from langchain_core.messages import AIMessage
from langgraph.graph import StateGraph, START, END

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.state import (
    OrderState,
    Cart,
    CartItem,
    CartItemUnit,
)
from src.agents.nodes.tool_node import tool_node


def make_state(cart):
    return {
        "messages": [],
        "orderId": None,
        "restaurant_name": "Test Restaurant",
        "subdomain": "test",
        "cart": cart,
        "finished": False,
    }


def make_cart(quantity=2):
    return Cart(
        items=[
            CartItem(
                item_id="item-001",
                title="Chicken Biryani",
                units=[
                    CartItemUnit(
                        key="item-001|no_variant",
                        quantity=quantity,
                        base_price=220.0,
                    )
                ],
            )
        ]
    )


def run_tool(state, tool_name, args, tool_call_id):
    graph = StateGraph(OrderState)

    graph.add_node("tools", tool_node)

    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)

    compiled = graph.compile()

    state["messages"] = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": tool_name,
                    "args": args,
                    "id": tool_call_id,
                    "type": "tool_call",
                }
            ],
        )
    ]

    return compiled.invoke(state)


def test_remove_one_item():
    state = make_state(make_cart(2))

    result = run_tool(
        state,
        "remove_from_cart",
        {
            "item_id": "item-001",
            "title": "Chicken Biryani",
            "new_item": {
                "key": "item-001|no_variant",
                "quantity": 1,
                "base_price": 220.0,
            },
        },
        "test-remove-one",
    )

    cart = result["cart"]

    assert len(cart.items) == 1
    assert cart.items[0].units[0].quantity == 1


def test_remove_entire_item():
    state = make_state(make_cart(1))

    result = run_tool(
        state,
        "remove_from_cart",
        {
            "item_id": "item-001",
            "title": "Chicken Biryani",
            "new_item": {
                "key": "item-001|no_variant",
                "quantity": 1,
                "base_price": 220.0,
            },
        },
        "test-remove-all",
    )

    assert result["cart"].items == []


def test_remove_more_than_available():
    state = make_state(make_cart(2))

    result = run_tool(
        state,
        "remove_from_cart",
        {
            "item_id": "item-001",
            "title": "Chicken Biryani",
            "new_item": {
                "key": "item-001|no_variant",
                "quantity": 5,
                "base_price": 220.0,
            },
        },
        "test-remove-too-many",
    )

    cart = result["cart"]

    assert len(cart.items) == 1
    assert cart.items[0].units[0].quantity == 2


def test_remove_nonexistent_item():
    state = make_state(make_cart(2))

    result = run_tool(
        state,
        "remove_from_cart",
        {
            "item_id": "item-999",
            "title": "Pizza",
            "new_item": {
                "key": "item-999|no_variant",
                "quantity": 1,
                "base_price": 300.0,
            },
        },
        "test-remove-missing",
    )

    cart = result["cart"]

    assert len(cart.items) == 1
    assert cart.items[0].item_id == "item-001"
    assert cart.items[0].units[0].quantity == 2


def test_clear_cart():
    state = make_state(make_cart(2))

    result = run_tool(
        state,
        "clear_cart",
        {},
        "test-clear",
    )

    assert result["cart"].items == []


def test_clear_empty_cart():
    state = make_state(Cart(items=[]))

    result = run_tool(
        state,
        "clear_cart",
        {},
        "test-clear-empty",
    )

    assert result["cart"].items == []