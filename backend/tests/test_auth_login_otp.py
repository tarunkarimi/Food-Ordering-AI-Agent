"""Login OTP API tests."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from src.api.routes import auth
from src.db.database import SessionLocal
from src.db.models import User, UserVerificationCode
from src.main import app


client = TestClient(app)


def _unique_email() -> str:
    return f"login-otp-{uuid4().hex}@example.com"


def _unique_phone() -> str:
    return f"+9198{uuid4().int % 100_000_000:08d}"


def _verify_email_user(user_id: int) -> None:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        user.email_verified = True
        db.commit()


def _verify_phone_user(user_id: int) -> None:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        user.phone_verified = True
        db.commit()


def test_request_login_otp_for_verified_email(
    monkeypatch,
) -> None:
    email = _unique_email()

    signup = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "StrongPassword123",
        },
    )

    assert signup.status_code == 201
    user_id = signup.json()["id"]

    _verify_email_user(user_id)

    monkeypatch.setattr(
        auth,
        "generate_otp",
        lambda: "123456",
    )

    response = client.post(
        "/api/auth/login/otp/request",
        json={"email": email},
    )

    assert response.status_code == 202

    with SessionLocal() as db:
        code = db.scalar(
            select(UserVerificationCode)
            .where(
                UserVerificationCode.user_id == user_id,
                UserVerificationCode.channel == "email",
                UserVerificationCode.purpose == "login",
                UserVerificationCode.verified_at.is_(None),
            )
            .order_by(
                UserVerificationCode.id.desc()
            )
        )

        assert code is not None
        assert code.code_hash != "123456"
        assert code.attempts == 0


def test_request_login_otp_for_verified_phone(
    monkeypatch,
) -> None:
    phone = _unique_phone()

    signup = client.post(
        "/api/auth/signup",
        json={
            "phone": phone,
            "password": "StrongPassword123",
        },
    )

    assert signup.status_code == 201
    user_id = signup.json()["id"]

    _verify_phone_user(user_id)

    monkeypatch.setattr(
        auth,
        "generate_otp",
        lambda: "654321",
    )

    response = client.post(
        "/api/auth/login/otp/request",
        json={"phone": phone},
    )

    assert response.status_code == 202

    with SessionLocal() as db:
        code = db.scalar(
            select(UserVerificationCode)
            .where(
                UserVerificationCode.user_id == user_id,
                UserVerificationCode.channel == "phone",
                UserVerificationCode.purpose == "login",
                UserVerificationCode.verified_at.is_(None),
            )
            .order_by(
                UserVerificationCode.id.desc()
            )
        )

        assert code is not None
        assert code.code_hash != "654321"


def test_verify_email_login_otp_succeeds(
    monkeypatch,
) -> None:
    email = _unique_email()

    signup = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "StrongPassword123",
        },
    )

    assert signup.status_code == 201
    user_id = signup.json()["id"]

    _verify_email_user(user_id)

    monkeypatch.setattr(
        auth,
        "generate_otp",
        lambda: "123456",
    )

    request = client.post(
        "/api/auth/login/otp/request",
        json={"email": email},
    )

    assert request.status_code == 202

    response = client.post(
        "/api/auth/login/otp/verify",
        json={
            "email": email,
            "code": "123456",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["id"] == user_id
    assert data["email"] == email
    assert data["phone"] is None
    assert data["email_verified"] is True
    assert data["is_active"] is True


def test_verify_phone_login_otp_succeeds(
    monkeypatch,
) -> None:
    phone = _unique_phone()

    signup = client.post(
        "/api/auth/signup",
        json={
            "phone": phone,
            "password": "StrongPassword123",
        },
    )

    assert signup.status_code == 201
    user_id = signup.json()["id"]

    _verify_phone_user(user_id)

    monkeypatch.setattr(
        auth,
        "generate_otp",
        lambda: "654321",
    )

    request = client.post(
        "/api/auth/login/otp/request",
        json={"phone": phone},
    )

    assert request.status_code == 202

    response = client.post(
        "/api/auth/login/otp/verify",
        json={
            "phone": phone,
            "code": "654321",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["id"] == user_id
    assert data["email"] is None
    assert data["phone"] == phone
    assert data["phone_verified"] is True
    assert data["is_active"] is True


def test_wrong_login_otp_increments_attempts(
    monkeypatch,
) -> None:
    email = _unique_email()

    signup = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "StrongPassword123",
        },
    )

    assert signup.status_code == 201
    user_id = signup.json()["id"]

    _verify_email_user(user_id)

    monkeypatch.setattr(
        auth,
        "generate_otp",
        lambda: "123456",
    )

    assert client.post(
        "/api/auth/login/otp/request",
        json={"email": email},
    ).status_code == 202

    response = client.post(
        "/api/auth/login/otp/verify",
        json={
            "email": email,
            "code": "000000",
        },
    )

    assert response.status_code == 400
    assert "4 attempt(s) remaining" in response.json()["detail"]

    with SessionLocal() as db:
        code = db.scalar(
            select(UserVerificationCode)
            .where(
                UserVerificationCode.user_id == user_id,
                UserVerificationCode.channel == "email",
                UserVerificationCode.purpose == "login",
            )
            .order_by(
                UserVerificationCode.id.desc()
            )
        )

        assert code is not None
        assert code.attempts == 1


def test_login_otp_blocks_after_max_attempts(
    monkeypatch,
) -> None:
    email = _unique_email()

    signup = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "StrongPassword123",
        },
    )

    assert signup.status_code == 201
    user_id = signup.json()["id"]

    _verify_email_user(user_id)

    monkeypatch.setattr(
        auth,
        "generate_otp",
        lambda: "123456",
    )

    assert client.post(
        "/api/auth/login/otp/request",
        json={"email": email},
    ).status_code == 202

    for _ in range(5):
        response = client.post(
            "/api/auth/login/otp/verify",
            json={
                "email": email,
                "code": "000000",
            },
        )
        assert response.status_code == 400

    response = client.post(
        "/api/auth/login/otp/verify",
        json={
            "email": email,
            "code": "123456",
        },
    )

    assert response.status_code == 429


def test_login_otp_expiry_is_enforced(
    monkeypatch,
) -> None:
    email = _unique_email()

    signup = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "StrongPassword123",
        },
    )

    assert signup.status_code == 201
    user_id = signup.json()["id"]

    _verify_email_user(user_id)

    monkeypatch.setattr(
        auth,
        "generate_otp",
        lambda: "123456",
    )

    assert client.post(
        "/api/auth/login/otp/request",
        json={"email": email},
    ).status_code == 202

    with SessionLocal() as db:
        code = db.scalar(
            select(UserVerificationCode)
            .where(
                UserVerificationCode.user_id == user_id,
                UserVerificationCode.channel == "email",
                UserVerificationCode.purpose == "login",
            )
            .order_by(
                UserVerificationCode.id.desc()
            )
        )

        assert code is not None
        code.expires_at = (
            datetime.now(timezone.utc)
            - timedelta(minutes=1)
        )
        db.commit()

    response = client.post(
        "/api/auth/login/otp/verify",
        json={
            "email": email,
            "code": "123456",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Verification code has expired."
    )


def test_new_login_otp_invalidates_previous_code(
    monkeypatch,
) -> None:
    email = _unique_email()

    signup = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "StrongPassword123",
        },
    )

    assert signup.status_code == 201
    user_id = signup.json()["id"]

    _verify_email_user(user_id)

    generated_codes = iter(
        ["123456", "654321"]
    )

    monkeypatch.setattr(
        auth,
        "generate_otp",
        lambda: next(generated_codes),
    )

    assert client.post(
        "/api/auth/login/otp/request",
        json={"email": email},
    ).status_code == 202

    assert client.post(
        "/api/auth/login/otp/request",
        json={"email": email},
    ).status_code == 202

    old_code_response = client.post(
        "/api/auth/login/otp/verify",
        json={
            "email": email,
            "code": "123456",
        },
    )

    assert old_code_response.status_code == 400
    assert old_code_response.json()["detail"] == (
        "Invalid verification code. "
        "4 attempt(s) remaining."
    )

    new_code_response = client.post(
        "/api/auth/login/otp/verify",
        json={
            "email": email,
            "code": "654321",
        },
    )

    assert new_code_response.status_code == 200


def test_login_otp_rejects_unverified_email() -> None:
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
        "/api/auth/login/otp/request",
        json={"email": email},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Email address is not verified."
    )


def test_login_otp_rejects_unknown_email() -> None:
    response = client.post(
        "/api/auth/login/otp/request",
        json={"email": _unique_email()},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == (
        "Unable to start OTP login."
    )


def test_login_otp_rejects_inactive_user(
    monkeypatch,
) -> None:
    email = _unique_email()

    signup = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "StrongPassword123",
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
        "/api/auth/login/otp/request",
        json={"email": email},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "User account is inactive."
    )


def test_login_otp_rejects_email_and_phone_together() -> None:
    response = client.post(
        "/api/auth/login/otp/request",
        json={
            "email": _unique_email(),
            "phone": _unique_phone(),
        },
    )

    assert response.status_code == 422


def test_login_otp_requires_identity() -> None:
    response = client.post(
        "/api/auth/login/otp/request",
        json={},
    )

    assert response.status_code == 422


def test_verify_login_otp_requires_identity() -> None:
    response = client.post(
        "/api/auth/login/otp/verify",
        json={"code": "123456"},
    )

    assert response.status_code == 422


def test_login_otp_normalizes_email_case(
    monkeypatch,
) -> None:
    email = _unique_email()

    signup = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "StrongPassword123",
        },
    )

    assert signup.status_code == 201
    user_id = signup.json()["id"]

    _verify_email_user(user_id)

    monkeypatch.setattr(
        auth,
        "generate_otp",
        lambda: "123456",
    )

    response = client.post(
        "/api/auth/login/otp/request",
        json={
            "email": email.upper(),
        },
    )

    assert response.status_code == 202

    response = client.post(
        "/api/auth/login/otp/verify",
        json={
            "email": email.upper(),
            "code": "123456",
        },
    )

    assert response.status_code == 200
    assert response.json()["id"] == user_id


def test_login_otp_rejects_reuse(
    monkeypatch,
) -> None:
    email = _unique_email()

    signup = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "StrongPassword123",
        },
    )

    assert signup.status_code == 201
    user_id = signup.json()["id"]

    _verify_email_user(user_id)

    monkeypatch.setattr(
        auth,
        "generate_otp",
        lambda: "123456",
    )

    assert client.post(
        "/api/auth/login/otp/request",
        json={"email": email},
    ).status_code == 202

    first = client.post(
        "/api/auth/login/otp/verify",
        json={
            "email": email,
            "code": "123456",
        },
    )

    assert first.status_code == 200

    second = client.post(
        "/api/auth/login/otp/verify",
        json={
            "email": email,
            "code": "123456",
        },
    )

    assert second.status_code == 400
    assert second.json()["detail"] == (
        "No active login verification code found."
    )