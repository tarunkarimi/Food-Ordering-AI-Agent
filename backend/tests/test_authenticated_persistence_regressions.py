"""Authenticated session and chat-cart persistence regression coverage."""

from uuid import uuid4

import jwt
import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from src.configs.config import config
from src.api.routes.chats import chat_agent_service
from src.db.database import SessionLocal
from src.db.models import User, UserSession
from src.main import app
from src.security.jwt import ALGORITHM


client = TestClient(app)

MENU_ITEM = {
    "id": "persistence-regression-item",
    "title": "Persistence Regression Bowl",
    "base_price": 12.5,
    "variations": [],
}


@pytest.fixture(autouse=True)
def prevent_external_side_effects(monkeypatch):
    """Make unexpected provider, menu, or order-service calls fail closed."""

    def reject_external_call(*args, **kwargs):
        pytest.fail("An external side effect was attempted by this regression test.")

    def fake_menu(*args, **kwargs):
        return [MENU_ITEM], None

    monkeypatch.setattr("src.api.routes.auth.deliver_verification_code", reject_external_call)
    monkeypatch.setattr("src.api.routes.chats._fetch_menu_items", fake_menu)

    for method_name in ("get", "post", "put", "patch", "delete", "head", "options", "request"):
        monkeypatch.setattr(requests, method_name, reject_external_call)


@pytest.fixture
def create_test_user():
    """Create verified users and delete only those users after the test."""

    created_user_ids = []

    def create_user():
        from src.security.passwords import hash_password

        email = f"persistence-regression-{uuid4().hex}@example.com"
        with SessionLocal() as db:
            user = User(
                email=email,
                phone=None,
                password_hash=hash_password("SyntheticTestPassword123!"),
                email_verified=True,
                phone_verified=False,
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            created_user_ids.append(user.id)
            return email, user.id

    yield create_user

    if created_user_ids:
        with SessionLocal() as db:
            db.execute(delete(User).where(User.id.in_(created_user_ids)))
            db.commit()


@pytest.fixture
def graph_thread_ids():
    """Track only this test's in-memory LangGraph checkpoint threads."""

    thread_ids = []
    yield thread_ids

    for thread_id in thread_ids:
        chat_agent_service.agent.checkpointer.delete_thread(thread_id)


def _login(email: str) -> str:
    response = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": "SyntheticTestPassword123!",
        },
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _claims(token: str) -> dict:
    return jwt.decode(token, config.JWT_SECRET_KEY, algorithms=[ALGORITHM])


def _find_cart(value):
    """Find the cart in the serialized LangGraph state response."""

    if isinstance(value, dict):
        cart = value.get("cart")
        if isinstance(cart, dict) and isinstance(cart.get("items"), list):
            return cart
        if isinstance(value.get("items"), list) and "cart" not in value:
            return value
        for nested in value.values():
            result = _find_cart(nested)
            if result is not None:
                return result
    elif isinstance(value, list):
        for nested in value:
            result = _find_cart(nested)
            if result is not None:
                return result
    return None


def test_authenticated_chat_cart_restores_from_database_and_is_user_scoped(
    create_test_user,
    graph_thread_ids,
):
    email_a, user_a_id = create_test_user()
    email_b, user_b_id = create_test_user()
    token_a = _login(email_a)
    token_b = _login(email_b)
    claims_a = _claims(token_a)
    claims_b = _claims(token_b)
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # The login sessions must be persisted and remain bound to their owners.
    with SessionLocal() as db:
        session_a = db.get(UserSession, claims_a["sid"])
        session_b = db.get(UserSession, claims_b["sid"])
        assert session_a is not None and session_a.user_id == user_a_id
        assert session_b is not None and session_b.user_id == user_b_id

    same_client_session_id = f"shared-client-session-{uuid4().hex}"
    restored_session_id = f"restored-session-{uuid4().hex}"
    graph_thread_ids.extend(
        [
            f"user:{user_a_id}:session:{same_client_session_id}",
            f"user:{user_a_id}:session:{restored_session_id}",
            f"user:{user_b_id}:session:{same_client_session_id}",
        ]
    )
    add_response = client.post(
        "/api/chats/cart/add",
        headers=headers_a,
        json={
            "session_id": same_client_session_id,
            "restaurant_name": "Persistence Test Restaurant",
            "subdomain": "persistence-test",
            "item_id": MENU_ITEM["id"],
            "title": MENU_ITEM["title"],
            "quantity": 2,
        },
    )
    assert add_response.status_code == 200

    # A new graph session simulates browser/session restoration from the DB.
    restored_response = client.get(
        "/api/chats/state",
        params={
            "session_id": restored_session_id,
            "restaurant_name": "Persistence Test Restaurant",
            "subdomain": "persistence-test",
        },
        headers=headers_a,
    )
    assert restored_response.status_code == 200
    restored_cart = _find_cart(restored_response.json())
    assert restored_cart is not None
    assert len(restored_cart["items"]) == 1
    restored_item = restored_cart["items"][0]
    assert restored_item["item_id"] == MENU_ITEM["id"]
    assert restored_item["title"] == MENU_ITEM["title"]
    assert restored_item["units"][0]["quantity"] == 2

    # The same client-provided session ID is namespaced by authenticated user.
    other_user_response = client.get(
        "/api/chats/state",
        params={
            "session_id": same_client_session_id,
            "restaurant_name": "Persistence Test Restaurant",
            "subdomain": "persistence-test",
        },
        headers=headers_b,
    )
    assert other_user_response.status_code == 200
    other_user_cart = _find_cart(other_user_response.json())
    assert other_user_cart is not None
    assert other_user_cart["items"] == []

    # Revoking one persisted login session does not revoke another user's.
    assert client.get("/api/auth/me", headers=headers_a).status_code == 200
    assert client.get("/api/auth/me", headers=headers_b).status_code == 200
    logout = client.post("/api/auth/logout", headers=headers_a)
    assert logout.status_code == 200
    assert client.get("/api/auth/me", headers=headers_a).status_code == 401
    assert client.get("/api/auth/me", headers=headers_b).status_code == 200

    with SessionLocal() as db:
        revoked_session = db.scalar(
            select(UserSession).where(UserSession.id == claims_a["sid"])
        )
        active_session = db.scalar(
            select(UserSession).where(UserSession.id == claims_b["sid"])
        )
        assert revoked_session is not None and revoked_session.revoked_at is not None
        assert active_session is not None and active_session.revoked_at is None
