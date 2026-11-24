from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from unittest.mock import Mock, patch

import requests
import pytest

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
        "order_status": None,
        "order_confirmation_pending": False,
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

    state["messages"] = list(state.get("messages", [])) + [
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


def menu_response(items=None):
    response = Mock()
    response.json.return_value = {
        "restaurant_name": "Test Restaurant",
        "subdomain": "test",
        "items": items
        if items is not None
        else [
            {
                "id": "item-001",
                "title": "Chicken Biryani",
                "base_price": 220.0,
                "variations": [],
            }
        ]
    }
    response.raise_for_status.return_value = None
    return response


def variation_menu_response():
    return menu_response(
        items=[
            {
                "id": "item-001",
                "title": "Chicken Biryani",
                "base_price": 220.0,
                "variations": [
                    {"id": "regular", "name": "Regular", "price": "220"},
                    {"id": "large", "name": "Large", "price": "280"},
                ],
            }
        ]
    )


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


def test_remove_cart_targets_only_selected_variation():
    state = make_state(
        Cart(
            items=[
                CartItem(
                    item_id="item-001",
                    title="Chicken Biryani",
                    units=[
                        CartItemUnit(
                            key="item-001|regular",
                            quantity=2,
                            base_price=220.0,
                            variation={
                                "id": "regular",
                                "name": "Regular",
                                "price": "220",
                            },
                        ),
                        CartItemUnit(
                            key="item-001|large",
                            quantity=3,
                            base_price=280.0,
                            variation={
                                "id": "large",
                                "name": "Large",
                                "price": "280",
                            },
                        ),
                    ],
                )
            ]
        )
    )

    result = run_tool(
        state,
        "remove_from_cart",
        {
            "item_id": "item-001",
            "title": "Chicken Biryani",
            "new_item": {
                "key": "item-001|large",
                "quantity": 1,
                "base_price": 1.0,
                "variation": {
                    "id": "large",
                    "name": "Large",
                    "price": "1",
                },
            },
        },
        "test-remove-large-only",
    )

    units = result["cart"].items[0].units

    assert len(units) == 2
    assert (
        next(
            unit
            for unit in units
            if unit.key == "item-001|regular"
        ).quantity
        == 2
    )
    assert (
        next(
            unit
            for unit in units
            if unit.key == "item-001|large"
        ).quantity
        == 2
    )


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


def test_add_cart_uses_authoritative_large_variation_price():
    state = make_state(Cart(items=[]))

    with patch(
        "src.agents.tools.cart.requests.get",
        return_value=variation_menu_response(),
    ):
        result = run_tool(
            state,
            "add_cart",
            {
                "item_id": "item-001",
                "title": "Chicken Biryani",
                "new_item": {
                    "key": "item-001|large",
                    "quantity": 2,
                    "base_price": 1.0,
                    "variation": {
                        "id": "large",
                        "name": "Large",
                        "price": "1",
                    },
                },
            },
            "test-add-large",
        )

    unit = result["cart"].items[0].units[0]

    assert unit.key == "item-001|large"
    assert unit.quantity == 2
    assert unit.base_price == 280.0
    assert unit.variation is not None
    assert unit.variation.id == "large"
    assert unit.variation.name == "Large"
    assert unit.variation.price == "280"


def test_add_cart_requires_variation_for_multi_variation_item():
    state = make_state(Cart(items=[]))

    with patch(
        "src.agents.tools.cart.requests.get",
        return_value=variation_menu_response(),
    ):
        result = run_tool(
            state,
            "add_cart",
            {
                "item_id": "item-001",
                "title": "Chicken Biryani",
                "new_item": {
                    "key": "item-001|no_variant",
                    "quantity": 2,
                    "base_price": 220.0,
                },
            },
            "test-add-missing-variation",
        )

    assert result["cart"].items == []


def test_add_cart_rejects_invalid_variation():
    state = make_state(Cart(items=[]))

    with patch(
        "src.agents.tools.cart.requests.get",
        return_value=variation_menu_response(),
    ):
        result = run_tool(
            state,
            "add_cart",
            {
                "item_id": "item-001",
                "title": "Chicken Biryani",
                "new_item": {
                    "key": "item-001|medium",
                    "quantity": 1,
                    "base_price": 250.0,
                    "variation": {
                        "id": "medium",
                        "name": "Medium",
                        "price": "250",
                    },
                },
            },
            "test-add-invalid-variation",
        )

    assert result["cart"].items == []


def test_add_cart_same_variation_combines_quantity_and_preserves_authoritative_price():
    state = make_state(Cart(items=[]))

    with patch(
        "src.agents.tools.cart.requests.get",
        return_value=variation_menu_response(),
    ):
        first = run_tool(
            state,
            "add_cart",
            {
                "item_id": "item-001",
                "title": "Chicken Biryani",
                "new_item": {
                    "key": "item-001|large",
                    "quantity": 2,
                    "base_price": 280.0,
                    "variation": {
                        "id": "large",
                        "name": "Large",
                        "price": "280",
                    },
                },
            },
            "test-add-large-one",
        )

        second = run_tool(
            first,
            "add_cart",
            {
                "item_id": "item-001",
                "title": "Chicken Biryani",
                "new_item": {
                    "key": "item-001|large",
                    "quantity": 3,
                    "base_price": 999.0,
                    "variation": {
                        "id": "large",
                        "name": "Large",
                        "price": "999",
                    },
                },
            },
            "test-add-large-two",
        )

    assert len(second["cart"].items) == 1
    assert len(second["cart"].items[0].units) == 1

    unit = second["cart"].items[0].units[0]

    assert unit.quantity == 5
    assert unit.base_price == 280.0
    assert unit.variation is not None
    assert unit.variation.id == "large"


def test_add_cart_different_variations_remain_separate_units():
    state = make_state(Cart(items=[]))

    with patch(
        "src.agents.tools.cart.requests.get",
        return_value=variation_menu_response(),
    ):
        state = run_tool(
            state,
            "add_cart",
            {
                "item_id": "item-001",
                "title": "Chicken Biryani",
                "new_item": {
                    "key": "item-001|regular",
                    "quantity": 2,
                    "base_price": 220.0,
                    "variation": {
                        "id": "regular",
                        "name": "Regular",
                        "price": "220",
                    },
                },
            },
            "test-add-regular",
        )

        state = run_tool(
            state,
            "add_cart",
            {
                "item_id": "item-001",
                "title": "Chicken Biryani",
                "new_item": {
                    "key": "item-001|large",
                    "quantity": 1,
                    "base_price": 280.0,
                    "variation": {
                        "id": "large",
                        "name": "Large",
                        "price": "280",
                    },
                },
            },
            "test-add-large",
        )

    assert len(state["cart"].items) == 1

    units = state["cart"].items[0].units

    assert len(units) == 2
    assert {unit.key for unit in units} == {
        "item-001|regular",
        "item-001|large",
    }
    assert {unit.base_price for unit in units} == {
        220.0,
        280.0,
    }


def test_add_cart_uses_authoritative_menu_price():
    state = make_state(Cart(items=[]))

    with patch(
        "src.agents.tools.cart.requests.get",
        return_value=menu_response(),
    ) as get:
        result = run_tool(
            state,
            "add_cart",
            {
                "item_id": "item-001",
                "title": "Chicken Biryani",
                "new_item": {
                    "key": "item-001|no_variant",
                    "quantity": 2,
                    "base_price": 1.0,
                },
            },
            "test-add-authoritative-price",
        )

    assert get.call_args.kwargs["timeout"] == 10
    assert result["cart"].items[0].units[0].base_price == 220.0


def test_add_cart_rejects_unavailable_menu_item_without_mutation():
    state = make_state(Cart(items=[]))
    unavailable = menu_response(
        items=[
            {
                "id": "item-001",
                "title": "Chicken Biryani",
                "base_price": 220.0,
                "variations": [],
                "available": False,
            }
        ]
    )

    with patch("src.agents.tools.cart.requests.get", return_value=unavailable):
        result = run_tool(
            state,
            "add_cart",
            {
                "item_id": "item-001",
                "title": "Chicken Biryani",
                "new_item": {
                    "key": "item-001|no_variant",
                    "quantity": 1,
                    "base_price": 220.0,
                },
            },
            "test-add-unavailable",
        )

    assert result["cart"].items == []
    assert "not currently available" in result["messages"][-1].content


@pytest.mark.parametrize("returned_subdomain", [None, "", "other"])
def test_add_cart_rejects_unconfirmed_menu_tenant_without_mutation(returned_subdomain):
    state = make_state(Cart(items=[]))
    response = menu_response()
    payload = response.json.return_value
    if returned_subdomain is None:
        payload.pop("subdomain")
    else:
        payload["subdomain"] = returned_subdomain

    with patch(
        "src.agents.tools.cart.requests.get", return_value=response
    ):
        result = run_tool(
            state,
            "add_cart",
            {
                "item_id": "item-001",
                "title": "Chicken Biryani",
                "new_item": {
                    "key": "item-001|no_variant",
                    "quantity": 1,
                    "base_price": 220.0,
                },
            },
            "test-add-wrong-tenant",
        )

    assert result["cart"].items == []
    assert "Cannot add item" in result["messages"][-1].content


def test_add_cart_rejects_invalid_quantity_and_menu_item():
    state = make_state(Cart(items=[]))

    with patch(
        "src.agents.tools.cart.requests.get"
    ) as get:
        invalid_quantity = run_tool(
            state,
            "add_cart",
            {
                "item_id": "item-001",
                "title": "Chicken Biryani",
                "new_item": {
                    "key": "item-001|no_variant",
                    "quantity": 0,
                    "base_price": 220.0,
                },
            },
            "test-add-zero",
        )

    get.assert_not_called()
    assert invalid_quantity["cart"].items == []

    with patch(
        "src.agents.tools.cart.requests.get",
        return_value=menu_response(),
    ):
        missing_item = run_tool(
            state,
            "add_cart",
            {
                "item_id": "item-999",
                "title": "Unknown",
                "new_item": {
                    "key": "item-999|no_variant",
                    "quantity": 1,
                    "base_price": 220.0,
                },
            },
            "test-add-missing",
        )

    assert missing_item["cart"].items == []


def test_get_menu_handles_service_timeout_without_crashing():
    state = make_state(Cart(items=[]))

    with patch(
        "src.agents.tools.cart.requests.get",
        side_effect=requests.Timeout,
    ):
        result = run_tool(
            state,
            "get_menu",
            {},
            "test-menu-timeout",
        )

    assert "timed out" in result["messages"][-1].content


def test_remove_cart_rejects_zero_quantity():
    state = make_state(make_cart(2))

    result = run_tool(
        state,
        "remove_from_cart",
        {
            "item_id": "item-001",
            "title": "Chicken Biryani",
            "new_item": {
                "key": "item-001|no_variant",
                "quantity": 0,
                "base_price": 220.0,
            },
        },
        "test-remove-zero",
    )

    assert result["cart"].items[0].units[0].quantity == 2


@pytest.mark.parametrize(
    ("cart", "expected_message"),
    [
        (Cart(items=[]), "Cart is empty"),
        (
            Cart(
                items=[
                    CartItem(
                        item_id="",
                        title="Chicken Biryani",
                        units=[CartItemUnit(key="item-001|no_variant", quantity=1, base_price=220.0)],
                    )
                ]
            ),
            "invalid items",
        ),
        (
            Cart(
                items=[
                    CartItem(
                        item_id="item-001",
                        title="Chicken Biryani",
                        units=[CartItemUnit(key="item-001|no_variant", quantity=1, base_price=-1.0)],
                    )
                ]
            ),
            "invalid items",
        ),
    ],
    ids=["empty-cart", "missing-item-identity", "invalid-price"],
)
def test_place_order_rejects_invalid_cart_without_checkout(cart, expected_message):
    state = make_state(cart)
    state.update(
        {
            "user_id": 77,
            "order_confirmation_pending": True,
            "messages": [HumanMessage(content="yes")],
        }
    )

    with patch("src.agents.tools.cart._place_order_with_outbox") as checkout:
        result = run_tool(state, "place_order", {}, "test-invalid-checkout")

    checkout.assert_not_called()
    assert expected_message.lower() in result["messages"][-1].content.lower()


def test_place_order_does_not_clear_cart_without_a_valid_order_id():
    state = make_state(make_cart(2))
    state.update(
        {
            "user_id": 77,
            "order_confirmation_pending": True,
            "messages": [HumanMessage(content="yes")],
        }
    )

    with patch(
        "src.agents.tools.cart._place_order_with_outbox",
        return_value=(
            {"order_id": "   ", "status": "confirmed", "subtotal": 440.0},
            2,
        ),
    ):
        result = run_tool(state, "place_order", {}, "test-invalid-order-id")

    assert result["cart"].items[0].units[0].quantity == 2
    assert result.get("orderId") is None
    assert result.get("order_history_persisted", False) is False
    assert "your cart is still saved" in result["messages"][-1].content.lower()
