"""Authentication OTP API tests."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from src.db.database import SessionLocal
from src.db.models import User, UserVerificationCode
from src.main import app


client = TestClient(app)


def _unique_email() -> str:
    return f"otp-{uuid4().hex}@example.com"


def _unique_phone() -> str:
    return f"+9198{uuid4().int % 100_000_000:08d}"


def _create_email_user() -> dict:
    response = client.post(
        "/api/auth/signup",
        json={
            "email": _unique_email(),
            "password": "StrongPassword123",
        },
    )

    assert response.status_code == 201
    return response.json()


def _create_phone_user() -> dict:
    response = client.post(
        "/api/auth/signup",
        json={
            "phone": _unique_phone(),
            "password": "StrongPassword123",
        },
    )

    assert response.status_code == 201
    return response.json()


def test_request_email_verification_code_creates_hashed_code(
    monkeypatch,
) -> None:
    user = _create_email_user()

    monkeypatch.setattr(
        "src.api.routes.auth.generate_otp",
        lambda: "123456",
    )

    response = client.post(
        "/api/auth/verification/request",
        json={
            "user_id": user["id"],
            "channel": "email",
            "purpose": "signup",
        },
    )

    assert response.status_code == 202
    assert "generated" in response.json()["message"].lower()

    with SessionLocal() as db:
        verification_code = db.scalar(
            select(UserVerificationCode)
            .where(
                UserVerificationCode.user_id == user["id"],
                UserVerificationCode.channel == "email",
                UserVerificationCode.purpose == "signup",
            )
            .order_by(UserVerificationCode.id.desc())
        )

        assert verification_code is not None
        assert verification_code.code_hash != "123456"
        assert verification_code.code_hash.startswith("$argon2")
        assert verification_code.verified_at is None
        assert verification_code.attempts == 0
        assert verification_code.expires_at > datetime.now(
            timezone.utc
        )


def test_request_phone_verification_code_creates_code(
    monkeypatch,
) -> None:
    user = _create_phone_user()

    monkeypatch.setattr(
        "src.api.routes.auth.generate_otp",
        lambda: "654321",
    )

    response = client.post(
        "/api/auth/verification/request",
        json={
            "user_id": user["id"],
            "channel": "phone",
            "purpose": "signup",
        },
    )

    assert response.status_code == 202

    with SessionLocal() as db:
        verification_code = db.scalar(
            select(UserVerificationCode)
            .where(
                UserVerificationCode.user_id == user["id"],
                UserVerificationCode.channel == "phone",
                UserVerificationCode.purpose == "signup",
            )
            .order_by(UserVerificationCode.id.desc())
        )

        assert verification_code is not None
        assert verification_code.code_hash != "654321"
        assert verification_code.verified_at is None


def test_request_verification_rejects_unknown_user() -> None:
    response = client.post(
        "/api/auth/verification/request",
        json={
            "user_id": 999999999,
            "channel": "email",
            "purpose": "signup",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found."


def test_request_email_verification_rejects_user_without_email(
) -> None:
    user = _create_phone_user()

    response = client.post(
        "/api/auth/verification/request",
        json={
            "user_id": user["id"],
            "channel": "email",
            "purpose": "signup",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "User does not have an email address."
    )


def test_request_phone_verification_rejects_user_without_phone(
) -> None:
    user = _create_email_user()

    response = client.post(
        "/api/auth/verification/request",
        json={
            "user_id": user["id"],
            "channel": "phone",
            "purpose": "signup",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "User does not have a phone number."
    )


def test_verify_email_otp_marks_email_verified(
    monkeypatch,
) -> None:
    user = _create_email_user()

    monkeypatch.setattr(
        "src.api.routes.auth.generate_otp",
        lambda: "123456",
    )

    request_response = client.post(
        "/api/auth/verification/request",
        json={
            "user_id": user["id"],
            "channel": "email",
            "purpose": "signup",
        },
    )

    assert request_response.status_code == 202

    response = client.post(
        "/api/auth/verification/verify",
        json={
            "user_id": user["id"],
            "channel": "email",
            "purpose": "signup",
            "code": "123456",
        },
    )

    assert response.status_code == 200
    assert response.json()["verified"] is True

    with SessionLocal() as db:
        db.expire_all()

        saved_user = db.get(User, user["id"])

        assert saved_user is not None
        assert saved_user.email_verified is True

        verification_code = db.scalar(
            select(UserVerificationCode)
            .where(
                UserVerificationCode.user_id == user["id"],
                UserVerificationCode.channel == "email",
                UserVerificationCode.purpose == "signup",
            )
            .order_by(UserVerificationCode.id.desc())
        )

        assert verification_code is not None
        assert verification_code.verified_at is not None
        assert verification_code.attempts == 1


def test_verify_phone_otp_marks_phone_verified(
    monkeypatch,
) -> None:
    user = _create_phone_user()

    monkeypatch.setattr(
        "src.api.routes.auth.generate_otp",
        lambda: "654321",
    )

    request_response = client.post(
        "/api/auth/verification/request",
        json={
            "user_id": user["id"],
            "channel": "phone",
            "purpose": "signup",
        },
    )

    assert request_response.status_code == 202

    response = client.post(
        "/api/auth/verification/verify",
        json={
            "user_id": user["id"],
            "channel": "phone",
            "purpose": "signup",
            "code": "654321",
        },
    )

    assert response.status_code == 200
    assert response.json()["verified"] is True

    with SessionLocal() as db:
        saved_user = db.get(User, user["id"])

        assert saved_user is not None
        assert saved_user.phone_verified is True


def test_verify_wrong_otp_increments_attempts(
    monkeypatch,
) -> None:
    user = _create_email_user()

    monkeypatch.setattr(
        "src.api.routes.auth.generate_otp",
        lambda: "123456",
    )

    request_response = client.post(
        "/api/auth/verification/request",
        json={
            "user_id": user["id"],
            "channel": "email",
            "purpose": "signup",
        },
    )

    assert request_response.status_code == 202

    response = client.post(
        "/api/auth/verification/verify",
        json={
            "user_id": user["id"],
            "channel": "email",
            "purpose": "signup",
            "code": "999999",
        },
    )

    assert response.status_code == 400
    assert "Invalid verification code" in response.json()["detail"]

    with SessionLocal() as db:
        verification_code = db.scalar(
            select(UserVerificationCode)
            .where(
                UserVerificationCode.user_id == user["id"],
                UserVerificationCode.channel == "email",
                UserVerificationCode.purpose == "signup",
            )
            .order_by(UserVerificationCode.id.desc())
        )

        assert verification_code is not None
        assert verification_code.attempts == 1


def test_verify_otp_cannot_exceed_max_attempts(
    monkeypatch,
) -> None:
    user = _create_email_user()

    monkeypatch.setattr(
        "src.api.routes.auth.generate_otp",
        lambda: "123456",
    )

    request_response = client.post(
        "/api/auth/verification/request",
        json={
            "user_id": user["id"],
            "channel": "email",
            "purpose": "signup",
        },
    )

    assert request_response.status_code == 202

    for _ in range(5):
        response = client.post(
            "/api/auth/verification/verify",
            json={
                "user_id": user["id"],
                "channel": "email",
                "purpose": "signup",
                "code": "999999",
            },
        )

        assert response.status_code == 400

    response = client.post(
        "/api/auth/verification/verify",
        json={
            "user_id": user["id"],
            "channel": "email",
            "purpose": "signup",
            "code": "123456",
        },
    )

    assert response.status_code == 429
    assert response.json()["detail"] == (
        "Maximum verification attempts exceeded."
    )


def test_expired_otp_is_rejected(
    monkeypatch,
) -> None:
    user = _create_email_user()

    monkeypatch.setattr(
        "src.api.routes.auth.generate_otp",
        lambda: "123456",
    )

    request_response = client.post(
        "/api/auth/verification/request",
        json={
            "user_id": user["id"],
            "channel": "email",
            "purpose": "signup",
        },
    )

    assert request_response.status_code == 202

    with SessionLocal() as db:
        verification_code = db.scalar(
            select(UserVerificationCode)
            .where(
                UserVerificationCode.user_id == user["id"],
                UserVerificationCode.channel == "email",
                UserVerificationCode.purpose == "signup",
            )
            .order_by(UserVerificationCode.id.desc())
        )

        assert verification_code is not None

        verification_code.expires_at = (
            datetime.now(timezone.utc) - timedelta(minutes=1)
        )

        db.commit()

    response = client.post(
        "/api/auth/verification/verify",
        json={
            "user_id": user["id"],
            "channel": "email",
            "purpose": "signup",
            "code": "123456",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Verification code has expired."
    )


def test_verified_otp_cannot_be_used_again(
    monkeypatch,
) -> None:
    user = _create_email_user()

    monkeypatch.setattr(
        "src.api.routes.auth.generate_otp",
        lambda: "123456",
    )

    request_response = client.post(
        "/api/auth/verification/request",
        json={
            "user_id": user["id"],
            "channel": "email",
            "purpose": "signup",
        },
    )

    assert request_response.status_code == 202

    first = client.post(
        "/api/auth/verification/verify",
        json={
            "user_id": user["id"],
            "channel": "email",
            "purpose": "signup",
            "code": "123456",
        },
    )

    assert first.status_code == 200

    second = client.post(
        "/api/auth/verification/verify",
        json={
            "user_id": user["id"],
            "channel": "email",
            "purpose": "signup",
            "code": "123456",
        },
    )

    assert second.status_code == 400
    assert second.json()["detail"] == (
        "No active verification code found."
    )


def test_requesting_new_otp_invalidates_previous_code(
    monkeypatch,
) -> None:
    user = _create_email_user()

    generated_codes = iter(["123456", "654321"])

    monkeypatch.setattr(
        "src.api.routes.auth.generate_otp",
        lambda: next(generated_codes),
    )

    first = client.post(
        "/api/auth/verification/request",
        json={
            "user_id": user["id"],
            "channel": "email",
            "purpose": "signup",
        },
    )

    assert first.status_code == 202

    second = client.post(
        "/api/auth/verification/request",
        json={
            "user_id": user["id"],
            "channel": "email",
            "purpose": "signup",
        },
    )

    assert second.status_code == 202

    old_code_response = client.post(
        "/api/auth/verification/verify",
        json={
            "user_id": user["id"],
            "channel": "email",
            "purpose": "signup",
            "code": "123456",
        },
    )

    assert old_code_response.status_code == 400

    new_code_response = client.post(
        "/api/auth/verification/verify",
        json={
            "user_id": user["id"],
            "channel": "email",
            "purpose": "signup",
            "code": "654321",
        },
    )

    assert new_code_response.status_code == 200
    assert new_code_response.json()["verified"] is True