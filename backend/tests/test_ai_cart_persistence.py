"""AI cart-tool to persistent-cart synchronization tests."""

from unittest.mock import Mock, patch

import requests
from sqlalchemy import delete
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.agents.nodes.chatbot import chatbot
from src.agents.state import Cart
from src.db.database import SessionLocal
from src.db.models import Cart as PersistentCart, OrderHistory, OrderOperation, User

from tests.test_cart_tools import make_cart, make_state, menu_response, run_tool
from tests.test_authenticated_cart import auth_headers, client, signup_and_login


def _create_authenticated_user(request):
    user_id, access_token = signup_and_login()

    def cleanup_synthetic_user():
        with SessionLocal() as db:
            db.execute(delete(User).where(User.id == user_id))
            db.commit()

    request.addfinalizer(cleanup_synthetic_user)
    return user_id, access_token


def _persistent_cart_snapshot(user_id):
    with SessionLocal() as db:
        cart = db.scalar(
            select(PersistentCart)
            .options(selectinload(PersistentCart.items))
            .where(PersistentCart.user_id == user_id)
        )

        if cart is None:
            return None

        return {
            "restaurant_name": cart.restaurant_name,
            "subdomain": cart.subdomain,
            "items": [
                {
                    "item_key": item.item_key,
                    "item_id": item.item_id,
                    "title": item.title,
                    "quantity": item.quantity,
                    "unit_price": str(item.unit_price),
                    "variation_id": item.variation_id,
                    "variation_name": item.variation_name,
                    "variation_price": (
                        str(item.variation_price)
                        if item.variation_price is not None
                        else None
                    ),
                }
                for item in cart.items
            ],
        }


def _authenticated_state(user_id, cart):
    state = make_state(cart)
    state["user_id"] = user_id
    return state


def _persist_state_cart(state):
    mock_model = Mock()
    mock_model.invoke.return_value = AIMessage(content="Cart updated.")

    with patch(
        "src.agents.nodes.chatbot._model_with_tools",
        mock_model,
    ):
        return chatbot(state)


def test_ai_add_cart_persists_to_authenticated_cart(request):
    user_id, _ = _create_authenticated_user(request)

    state = _authenticated_state(
        user_id,
        Cart(items=[]),
    )

    with patch(
        "src.agents.tools.cart.requests.get",
        return_value=menu_response(),
    ):
        updated_state = run_tool(
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
            "ai-add-persist",
        )

    _persist_state_cart(updated_state)

    snapshot = _persistent_cart_snapshot(user_id)

    assert snapshot is not None
    assert len(snapshot["items"]) == 1
    assert snapshot["items"][0]["item_id"] == "item-001"
    assert snapshot["items"][0]["quantity"] == 2
    assert snapshot["items"][0]["unit_price"] == "220.00"


def test_ai_remove_cart_persists_reduced_quantity(request):
    user_id, _ = _create_authenticated_user(request)

    state = _authenticated_state(
        user_id,
        make_cart(3),
    )

    _persist_state_cart(state)

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
        "ai-remove-persist",
    )

    _persist_state_cart(result)

    snapshot = _persistent_cart_snapshot(user_id)

    assert snapshot is not None
    assert len(snapshot["items"]) == 1
    assert snapshot["items"][0]["quantity"] == 2


def test_ai_clear_cart_persists_empty_cart(request):
    user_id, _ = _create_authenticated_user(request)

    state = _authenticated_state(
        user_id,
        make_cart(2),
    )

    _persist_state_cart(state)

    result = run_tool(
        state,
        "clear_cart",
        {},
        "ai-clear-persist",
    )

    _persist_state_cart(result)

    snapshot = _persistent_cart_snapshot(user_id)

    assert snapshot is not None
    assert snapshot["items"] == []

def test_ai_tool_mutations_do_not_cross_user_boundaries(request):
    user_a, _ = _create_authenticated_user(request)
    user_b, _ = _create_authenticated_user(request)

    state_a = _authenticated_state(
        user_a,
        make_cart(2),
    )

    state_b = _authenticated_state(
        user_b,
        make_cart(5),
    )

    _persist_state_cart(state_a)
    _persist_state_cart(state_b)

    result = run_tool(
        state_a,
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
        "ai-user-a-remove",
    )

    _persist_state_cart(result)

    snapshot_a = _persistent_cart_snapshot(user_a)
    snapshot_b = _persistent_cart_snapshot(user_b)

    assert snapshot_a["items"][0]["quantity"] == 1
    assert snapshot_b["items"][0]["quantity"] == 5


def test_ai_place_order_success_clears_persistent_cart(request):
    user_id, access_token = _create_authenticated_user(request)

    state = _authenticated_state(
        user_id,
        make_cart(2),
    )

    state["order_confirmation_pending"] = True
    state["messages"] = [
        HumanMessage(content="yes"),
    ]

    _persist_state_cart(state)

    successful_order = {
        "order_id": "ai-order-001",
        "status": "confirmed",
        "subtotal": 440.0,
    }

    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = successful_order

    with patch(
        "src.agents.tools.cart.requests.post",
        return_value=response,
    ):
        result = run_tool(
            state,
            "place_order",
            {},
            "ai-place-success",
        )

    assert result["cart"].items == []
    assert result["orderId"] == "ai-order-001"
    assert result["order_status"] == "confirmed"

    _persist_state_cart(result)

    snapshot = _persistent_cart_snapshot(user_id)

    assert snapshot is not None
    assert snapshot["items"] == []

    with SessionLocal() as db:
        order_history = db.scalar(
            select(OrderHistory).where(
                OrderHistory.user_id == user_id,
                OrderHistory.order_id == "ai-order-001",
            )
        )
        assert order_history is not None
        assert order_history.status == "confirmed"
        assert order_history.subdomain == "test"
        assert order_history.total_items == 2

    history_response = client.get(
        "/api/orders",
        headers=auth_headers(access_token),
    )
    assert history_response.status_code == 200
    assert any(
        order["order_id"] == "ai-order-001"
        for order in history_response.json()["orders"]
    )


def test_ai_place_order_failure_preserves_persistent_cart(request):
    user_id, _ = _create_authenticated_user(request)

    state = _authenticated_state(
        user_id,
        make_cart(2),
    )

    state["order_confirmation_pending"] = True
    state["messages"] = [
        HumanMessage(content="yes"),
    ]

    _persist_state_cart(state)

    failed_response = Mock()
    failed_response.raise_for_status.side_effect = requests.exceptions.RequestException(
        "order service unavailable"
    )

    with patch(
        "src.agents.tools.cart.requests.post",
        return_value=failed_response,
    ):
        result = run_tool(
            state,
            "place_order",
            {},
            "ai-place-failure",
        )

    snapshot = _persistent_cart_snapshot(user_id)

    assert snapshot is not None
    assert len(snapshot["items"]) == 1
    assert snapshot["items"][0]["quantity"] == 2
    assert result["cart"].items[0].units[0].quantity == 2


def test_ai_checkout_retry_reuses_intent_and_persists_one_order(request):
    user_id, _ = _create_authenticated_user(request)
    state = _authenticated_state(user_id, make_cart(2))
    state["order_confirmation_pending"] = True
    state["messages"] = [HumanMessage(content="yes")]
    _persist_state_cart(state)

    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "order_id": "ai-order-retry-001",
        "status": "confirmed",
        "subtotal": 440.0,
    }

    with patch(
        "src.agents.tools.cart.requests.post",
        side_effect=[requests.Timeout("synthetic timeout"), response],
    ) as mock_post:
        failed = run_tool(state, "place_order", {}, "ai-place-timeout")
        assert "still saved" in failed["messages"][-1].content
        assert failed["cart"].items[0].units[0].quantity == 2

        retry_state = dict(failed)
        retry_state["messages"] = [HumanMessage(content="yes")]
        retried = run_tool(retry_state, "place_order", {}, "ai-place-retry")

    assert mock_post.call_count == 2
    first_headers = mock_post.call_args_list[0].kwargs["headers"]
    second_headers = mock_post.call_args_list[1].kwargs["headers"]
    assert first_headers["Idempotency-Key"] == second_headers["Idempotency-Key"]
    assert isinstance(first_headers.get("X-Menu-Service-Key"), str)
    assert len(first_headers["X-Menu-Service-Key"]) >= 32
    assert mock_post.call_args_list[0].kwargs["json"] == mock_post.call_args_list[1].kwargs["json"]
    assert retried["orderId"] == "ai-order-retry-001"
    assert retried["order_history_persisted"] is True
    assert retried["cart"].items == []

    with SessionLocal() as db:
        orders = list(
            db.scalars(
                select(OrderHistory).where(
                    OrderHistory.user_id == user_id,
                    OrderHistory.order_id == "ai-order-retry-001",
                )
            )
        )
        operations = list(
            db.scalars(
                select(OrderOperation).where(
                    OrderOperation.user_id == user_id,
                    OrderOperation.operation_type == "chat_checkout",
                )
            )
        )
        assert len(orders) == 1
        assert len(operations) == 1
        assert operations[0].status == "completed"
        assert operations[0].attempts == 2

    _persist_state_cart(retried)
    snapshot = _persistent_cart_snapshot(user_id)
    assert snapshot is not None
    assert snapshot["items"] == []
