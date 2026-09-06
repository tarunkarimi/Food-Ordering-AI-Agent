"""Signup API tests."""

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from src.db.database import SessionLocal
from src.db.models import User
from src.main import app


client = TestClient(app)


def test_signup_with_email_creates_unverified_user() -> None:
    email = f"testuser-{uuid4().hex}@example.com"

    response = client.post(
        "/api/auth/signup",
        json={
            "email": f"  {email.upper()}  ",
            "password": "StrongPassword123",
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["email"] == email
    assert data["phone"] is None
    assert data["email_verified"] is False
    assert data["phone_verified"] is False
    assert data["is_active"] is True

    with SessionLocal() as db:
        user = db.scalar(
            select(User).where(User.id == data["id"])
        )

        assert user is not None
        assert user.email == email
        assert user.phone is None
        assert user.password_hash != "StrongPassword123"


def test_signup_with_phone_creates_unverified_user() -> None:
    # +91 followed by a unique 10-digit Indian mobile number.
    phone = f"+9198{uuid4().int % 100_000_000:08d}"

    response = client.post(
        "/api/auth/signup",
        json={
            "phone": phone,
            "password": "StrongPassword123",
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["email"] is None
    assert data["phone"] == phone
    assert data["email_verified"] is False
    assert data["phone_verified"] is False
    assert data["is_active"] is True

    with SessionLocal() as db:
        user = db.scalar(
            select(User).where(User.id == data["id"])
        )

        assert user is not None
        assert user.phone == phone
        assert user.email is None
        assert user.password_hash != "StrongPassword123"


def test_signup_rejects_duplicate_email() -> None:
    email = f"duplicate-{uuid4().hex}@example.com"

    payload = {
        "email": email,
        "password": "StrongPassword123",
    }

    first = client.post("/api/auth/signup", json=payload)

    assert first.status_code == 201

    second = client.post("/api/auth/signup", json=payload)

    assert second.status_code == 409
    assert second.json()["detail"] == (
        "An account with this email or phone already exists."
    )


def test_signup_rejects_duplicate_phone() -> None:
    phone = f"+9198{uuid4().int % 100_000_000:08d}"

    first = client.post(
        "/api/auth/signup",
        json={
            "phone": phone,
            "password": "StrongPassword123",
        },
    )

    assert first.status_code == 201

    # Same number in a different formatting to verify normalization.
    formatted_phone = (
        f"+91 {phone[3:8]} {phone[8:]}"
    )

    second = client.post(
        "/api/auth/signup",
        json={
            "phone": formatted_phone,
            "password": "AnotherPassword123",
        },
    )

    assert second.status_code == 409
    assert second.json()["detail"] == (
        "An account with this email or phone already exists."
    )


def test_signup_rejects_email_and_phone_together() -> None:
    response = client.post(
        "/api/auth/signup",
        json={
            "email": f"both-{uuid4().hex}@example.com",
            "phone": "+919876543212",
            "password": "StrongPassword123",
        },
    )

    assert response.status_code == 422


def test_signup_rejects_missing_identity() -> None:
    response = client.post(
        "/api/auth/signup",
        json={
            "password": "StrongPassword123",
        },
    )

    assert response.status_code == 422


def test_signup_rejects_invalid_email() -> None:
    response = client.post(
        "/api/auth/signup",
        json={
            "email": "not-an-email",
            "password": "StrongPassword123",
        },
    )

    assert response.status_code == 422


def test_signup_rejects_invalid_phone() -> None:
    response = client.post(
        "/api/auth/signup",
        json={
            "phone": "123",
            "password": "StrongPassword123",
        },
    )

    assert response.status_code == 422


def test_signup_rejects_short_password() -> None:
    response = client.post(
        "/api/auth/signup",
        json={
            "email": f"short-password-{uuid4().hex}@example.com",
            "password": "short",
        },
    )

    assert response.status_code == 422


def test_signup_normalizes_email_case_for_duplicate_detection() -> None:
    email = f"casetest-{uuid4().hex}@example.com"

    first = client.post(
        "/api/auth/signup",
        json={
            "email": email.upper(),
            "password": "StrongPassword123",
        },
    )

    assert first.status_code == 201
    assert first.json()["email"] == email

    second = client.post(
        "/api/auth/signup",
        json={
            "email": email.lower(),
            "password": "AnotherPassword123",
        },
    )

    assert second.status_code == 409
    assert second.json()["detail"] == (
        "An account with this email or phone already exists."
    )