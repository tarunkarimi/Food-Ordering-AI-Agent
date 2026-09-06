"""Authentication dependency tests."""

from uuid import uuid4

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.api.dependencies import get_current_user
from src.db.database import SessionLocal
from src.db.models import User
from src.security.jwt import create_access_token


def _unique_email() -> str:
    return f"dependency-{uuid4().hex}@example.com"


def _create_user(
    *,
    is_active: bool = True,
) -> int:
    from src.security.passwords import hash_password

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


app = FastAPI()


@app.get("/protected")
def protected(user: User = Depends(get_current_user)) -> dict:
    return {
        "user_id": user.id,
        "email": user.email,
    }


client = TestClient(app)


def test_dependency_requires_authentication() -> None:
    response = client.get("/protected")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required."


def test_dependency_accepts_valid_token() -> None:
    user_id = _create_user()

    token = create_access_token(user_id)

    response = client.get(
        "/protected",
        headers={
            "Authorization": f"Bearer {token}",
        },
    )

    assert response.status_code == 200
    assert response.json()["user_id"] == user_id


def test_dependency_rejects_invalid_token() -> None:
    response = client.get(
        "/protected",
        headers={
            "Authorization": "Bearer invalid-token",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == (
        "Invalid or expired access token."
    )


def test_dependency_rejects_deleted_user() -> None:
    user_id = _create_user()

    token = create_access_token(user_id)

    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        db.delete(user)
        db.commit()

    response = client.get(
        "/protected",
        headers={
            "Authorization": f"Bearer {token}",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == (
        "Authenticated user no longer exists."
    )


def test_dependency_rejects_inactive_user() -> None:
    user_id = _create_user(is_active=False)

    token = create_access_token(user_id)

    response = client.get(
        "/protected",
        headers={
            "Authorization": f"Bearer {token}",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "User account is inactive."
    )