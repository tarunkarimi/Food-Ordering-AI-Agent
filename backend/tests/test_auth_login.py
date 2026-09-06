"""Password login API tests."""

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from src.db.database import SessionLocal
from src.db.models import User
from src.main import app
from src.security.passwords import hash_password


client = TestClient(app)


def _unique_email() -> str:
    return f"login-{uuid4().hex}@example.com"


def _unique_phone() -> str:
    return f"+9198{uuid4().int % 100_000_000:08d}"


def test_login_with_verified_email_and_password_succeeds() -> None:
    email = _unique_email()
    password = "StrongPassword123"

    signup = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": password,
        },
    )

    assert signup.status_code == 201
    user_id = signup.json()["id"]

    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        user.email_verified = True
        db.commit()

    response = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["id"] == user_id
    assert data["email"] == email
    assert data["phone"] is None
    assert data["email_verified"] is True
    assert data["phone_verified"] is False
    assert data["is_active"] is True


def test_login_with_verified_phone_and_password_succeeds() -> None:
    phone = _unique_phone()
    password = "StrongPassword123"

    signup = client.post(
        "/api/auth/signup",
        json={
            "phone": phone,
            "password": password,
        },
    )

    assert signup.status_code == 201
    user_id = signup.json()["id"]

    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        user.phone_verified = True
        db.commit()

    formatted_phone = f"+91 {phone[3:8]} {phone[8:]}"

    response = client.post(
        "/api/auth/login",
        json={
            "phone": formatted_phone,
            "password": password,
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["id"] == user_id
    assert data["email"] is None
    assert data["phone"] == phone
    assert data["phone_verified"] is True
    assert data["email_verified"] is False
    assert data["is_active"] is True


def test_login_normalizes_email_case() -> None:
    email = _unique_email()
    password = "StrongPassword123"

    signup = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": password,
        },
    )

    assert signup.status_code == 201
    user_id = signup.json()["id"]

    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        user.email_verified = True
        db.commit()

    response = client.post(
        "/api/auth/login",
        json={
            "email": email.upper(),
            "password": password,
        },
    )

    assert response.status_code == 200
    assert response.json()["id"] == user_id


def test_login_rejects_wrong_password() -> None:
    email = _unique_email()

    signup = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "CorrectPassword123",
        },
    )

    assert signup.status_code == 201
    user_id = signup.json()["id"]

    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        user.email_verified = True
        db.commit()

    response = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": "WrongPassword123",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials."


def test_login_rejects_unknown_email() -> None:
    response = client.post(
        "/api/auth/login",
        json={
            "email": _unique_email(),
            "password": "SomePassword123",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials."


def test_login_rejects_unknown_phone() -> None:
    response = client.post(
        "/api/auth/login",
        json={
            "phone": _unique_phone(),
            "password": "SomePassword123",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials."


def test_login_rejects_unverified_email() -> None:
    email = _unique_email()

    signup = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "StrongPassword123",
        },
    )

    assert signup.status_code == 201

    response = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": "StrongPassword123",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Account identity is not verified. "
        "Please verify your email or phone number first."
    )


def test_login_rejects_unverified_phone() -> None:
    phone = _unique_phone()

    signup = client.post(
        "/api/auth/signup",
        json={
            "phone": phone,
            "password": "StrongPassword123",
        },
    )

    assert signup.status_code == 201

    response = client.post(
        "/api/auth/login",
        json={
            "phone": phone,
            "password": "StrongPassword123",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Account identity is not verified. "
        "Please verify your email or phone number first."
    )


def test_login_rejects_inactive_user() -> None:
    email = _unique_email()
    password = "StrongPassword123"

    signup = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": password,
        },
    )

    assert signup.status_code == 201
    user_id = signup.json()["id"]

    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        user.email_verified = True
        user.is_active = False
        db.commit()

    response = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "User account is inactive."


def test_login_rejects_email_and_phone_together() -> None:
    response = client.post(
        "/api/auth/login",
        json={
            "email": _unique_email(),
            "phone": _unique_phone(),
            "password": "StrongPassword123",
        },
    )

    assert response.status_code == 422


def test_login_rejects_missing_identity() -> None:
    response = client.post(
        "/api/auth/login",
        json={
            "password": "StrongPassword123",
        },
    )

    assert response.status_code == 422


def test_login_rejects_invalid_phone() -> None:
    response = client.post(
        "/api/auth/login",
        json={
            "phone": "123",
            "password": "StrongPassword123",
        },
    )

    assert response.status_code == 422


def test_login_does_not_return_password_or_hash() -> None:
    email = _unique_email()
    password = "StrongPassword123"

    signup = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": password,
        },
    )

    assert signup.status_code == 201
    user_id = signup.json()["id"]

    with SessionLocal() as db:
        user = db.scalar(
            select(User).where(User.id == user_id)
        )
        assert user is not None
        user.email_verified = True
        db.commit()

    response = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert "password" not in data
    assert "password_hash" not in data