"""Authenticated user endpoint tests."""

from uuid import uuid4

from fastapi.testclient import TestClient

from src.db.database import SessionLocal
from src.db.models import User
from src.main import app
from src.security.passwords import hash_password
from src.services.sessions import create_user_session


client = TestClient(app)


def _unique_email() -> str:
    return f"me-{uuid4().hex}@example.com"


def _create_user(*, is_active: bool = True) -> int:
    with SessionLocal() as db:
        user = User(
            email=_unique_email(),
            phone=None,
            password_hash=hash_password("StrongPassword123"),
            email_verified=True,
            phone_verified=False,
            is_active=is_active,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id


def _create_session_token(user_id: int) -> str:
    with SessionLocal() as db:
        return create_user_session(db, user_id)


def test_me_requires_authentication() -> None:
    response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required."


def test_me_returns_authenticated_user() -> None:
    user_id = _create_user()
    token = _create_session_token(user_id)

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200

    data = response.json()

    assert data["id"] == user_id
    assert data["email"]
    assert data["phone"] is None
    assert data["email_verified"] is True
    assert data["phone_verified"] is False
    assert data["is_active"] is True

    assert "password" not in data
    assert "password_hash" not in data


def test_me_rejects_invalid_token() -> None:
    response = client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired access token."


def test_me_rejects_inactive_user() -> None:
    user_id = _create_user(is_active=False)
    token = _create_session_token(user_id)

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "User account is inactive."
