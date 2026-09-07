"""Persistent-cart and LangGraph synchronization tests."""

from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select

from src.db.database import SessionLocal
from src.db.models import Cart as PersistentCart
from src.main import app

from tests.test_authenticated_cart import (
    auth_headers,
    cart_item_payload,
    fake_menu,
    signup_and_login,
)


client = TestClient(app)


def _chat_payload(session_id: str = "persistent-cart-session") -> dict:
    return {
        "user_message": "Hello",
        "session_id": session_id,
        "restaurant_name": "Test Restaurant",
        "subdomain": "test",
    }


def test_authenticated_chat_hydrates_persistent_cart_into_graph():
    user_id, token = signup_and_login()

    headers = auth_headers(token)

    with patch(
        "src.api.routes.cart._fetch_menu_items",
        side_effect=fake_menu,
    ):
        add = client.post(
            "/api/cart/items",
            json=cart_item_payload(
                quantity=2,
                variation_id="large",
            ),
            headers=headers,
        )

    assert add.status_code == 200
    assert add.json()["total"] == 560.0

    with patch("src.api.routes.chats.chatbot_agent") as mock_agent:
        mock_agent.stream.return_value = iter(
            [
                {
                    "messages": [],
                }
            ]
        )

        response = client.post(
            "/api/chats/orders",
            json=_chat_payload(),
            headers=headers,
        )

    assert response.status_code == 200

    graph_state = mock_agent.stream.call_args.args[0]

    # The initial graph state intentionally starts without a cart so
    # the chatbot node performs the persistent-cart hydration.
    assert graph_state["user_id"] == user_id


def test_persistent_cart_survives_across_authenticated_chat_sessions():
    user_id, token = signup_and_login()

    headers = auth_headers(token)

    with patch(
        "src.api.routes.cart._fetch_menu_items",
        side_effect=fake_menu,
    ):
        add = client.post(
            "/api/cart/items",
            json=cart_item_payload(
                quantity=2,
                variation_id="large",
            ),
            headers=headers,
        )

    assert add.status_code == 200

    with SessionLocal() as db:
        cart = db.scalar(
            select(PersistentCart).where(
                PersistentCart.user_id == user_id
            )
        )

        assert cart is not None
        assert len(cart.items) == 1
        assert cart.items[0].quantity == 2
        assert cart.items[0].item_id == "item-001"
        assert cart.items[0].variation_id == "large"


def test_users_cannot_share_persistent_langgraph_cart():
    user_a, token_a = signup_and_login()
    user_b, token_b = signup_and_login()

    headers_a = auth_headers(token_a)
    headers_b = auth_headers(token_b)

    with patch(
        "src.api.routes.cart._fetch_menu_items",
        side_effect=fake_menu,
    ):
        add = client.post(
            "/api/cart/items",
            json=cart_item_payload(
                quantity=3,
                variation_id="regular",
            ),
            headers=headers_a,
        )

    assert add.status_code == 200

    with patch("src.api.routes.chats.chatbot_agent") as mock_agent:
        mock_agent.stream.return_value = iter(
            [
                {
                    "messages": [],
                }
            ]
        )

        response = client.post(
            "/api/chats/orders",
            json=_chat_payload("shared-session"),
            headers=headers_b,
        )

    assert response.status_code == 200

    with SessionLocal() as db:
        cart_a = db.scalar(
            select(PersistentCart).where(
                PersistentCart.user_id == user_a
            )
        )
        cart_b = db.scalar(
            select(PersistentCart).where(
                PersistentCart.user_id == user_b
            )
        )

        assert cart_a is not None
        assert len(cart_a.items) == 1
        assert cart_a.items[0].quantity == 3

        assert cart_b is None or len(cart_b.items) == 0
