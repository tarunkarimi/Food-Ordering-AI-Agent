"""Signup verification lifecycle tests."""

from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from src.db.database import SessionLocal
from src.db.models import User, UserVerificationCode
from src.main import app
from src.security.otp import verify_otp


client = TestClient(app)


def _unique_email() -> str:
    return f"verification-{uuid4().hex}@example.com"


def _unique_phone() -> str:
    return f"+9198{uuid4().int % 100_000_000:08d}"


def test_email_signup_creates_active_signup_verification_code() -> None:
    email = _unique_email()

    response = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "StrongPassword123",
        },
    )

    assert response.status_code == 201

    user_id = response.json()["id"]

    with SessionLocal() as db:
        code = db.scalar(
            select(UserVerificationCode)
            .where(
                UserVerificationCode.user_id == user_id,
                UserVerificationCode.channel == "email",
                UserVerificationCode.purpose == "signup",
            )
            .order_by(UserVerificationCode.id.desc())
        )

        assert code is not None
        assert code.verified_at is None
        assert code.attempts == 0
        assert code.expires_at > datetime.now(timezone.utc)
        assert code.code_hash
        assert len(code.code_hash) > 20
        assert code.code_hash != "000000"


def test_phone_signup_creates_active_signup_verification_code() -> None:
    phone = _unique_phone()

    response = client.post(
        "/api/auth/signup",
        json={
            "phone": phone,
            "password": "StrongPassword123",
        },
    )

    assert response.status_code == 201

    user_id = response.json()["id"]

    with SessionLocal() as db:
        code = db.scalar(
            select(UserVerificationCode)
            .where(
                UserVerificationCode.user_id == user_id,
                UserVerificationCode.channel == "phone",
                UserVerificationCode.purpose == "signup",
            )
            .order_by(UserVerificationCode.id.desc())
        )

        assert code is not None
        assert code.verified_at is None
        assert code.attempts == 0
        assert code.expires_at > datetime.now(timezone.utc)
        assert code.code_hash


def test_signup_response_never_exposes_verification_code() -> None:
    email = _unique_email()

    response = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "StrongPassword123",
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert "code" not in data
    assert "otp" not in data
    assert "verification_code" not in data
    assert "code_hash" not in data


def test_signup_verification_code_is_stored_as_a_hash() -> None:
    email = _unique_email()

    response = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "StrongPassword123",
        },
    )

    assert response.status_code == 201

    user_id = response.json()["id"]

    with SessionLocal() as db:
        code = db.scalar(
            select(UserVerificationCode)
            .where(
                UserVerificationCode.user_id == user_id,
                UserVerificationCode.channel == "email",
                UserVerificationCode.purpose == "signup",
            )
            .order_by(UserVerificationCode.id.desc())
        )

        assert code is not None

        # Argon2 hashes have a recognizable encoded format and should
        # never contain the six-digit OTP as plaintext.
        assert code.code_hash.startswith("$argon2")
        assert code.code_hash.isascii()

        # The stored hash must not itself be usable as an OTP.
        assert not verify_otp(code.code_hash, code.code_hash)
