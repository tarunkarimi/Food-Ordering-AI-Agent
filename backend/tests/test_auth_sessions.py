"""Persistent authentication-session tests."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import select

from src.configs.config import config
from src.db.database import SessionLocal
from src.db.models import User, UserSession
from src.main import app
from src.security.jwt import ALGORITHM


client = TestClient(app)


def unique_email() -> str:
    return f"session-{uuid4().hex}@example.com"


def signup_and_verify_email(email: str, password: str) -> int:
    response = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": password,
        },
    )

    assert response.status_code == 201
    user_id = response.json()["id"]

    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        user.email_verified = True
        db.commit()

    return user_id


def decode_token(token: str) -> dict:
    return jwt.decode(
        token,
        config.JWT_SECRET_KEY,
        algorithms=[ALGORITHM],
    )


def test_password_login_creates_persistent_session():
    email = unique_email()
    password = "StrongPassword123!"

    user_id = signup_and_verify_email(email, password)

    response = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )

    assert response.status_code == 200

    access_token = response.json()["access_token"]
    claims = decode_token(access_token)

    assert claims["sub"] == str(user_id)
    assert isinstance(claims["sid"], str)
    assert claims["sid"]
    assert isinstance(claims["jti"], str)
    assert claims["jti"]

    with SessionLocal() as db:
        session = db.get(UserSession, claims["sid"])

        assert session is not None
        assert session.user_id == user_id
        assert session.access_token_jti == claims["jti"]
        assert session.revoked_at is None
        assert session.expires_at > datetime.now(timezone.utc)


def test_session_bound_token_can_access_me():
    email = unique_email()
    password = "StrongPassword123!"

    signup_and_verify_email(email, password)

    login_response = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )

    assert login_response.status_code == 200

    token = login_response.json()["access_token"]

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["email"] == email


def test_logout_revokes_current_session():
    email = unique_email()
    password = "StrongPassword123!"

    user_id = signup_and_verify_email(email, password)

    login_response = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )

    assert login_response.status_code == 200

    token = login_response.json()["access_token"]
    claims = decode_token(token)

    logout_response = client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert logout_response.status_code == 200
    assert logout_response.json() == {
        "message": "Logged out successfully."
    }

    with SessionLocal() as db:
        session = db.get(UserSession, claims["sid"])

        assert session is not None
        assert session.user_id == user_id
        assert session.revoked_at is not None

    me_response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert me_response.status_code == 401
    assert me_response.json()["detail"] == (
        "Authenticated session has been revoked."
    )


def test_multiple_logins_create_independent_sessions():
    email = unique_email()
    password = "StrongPassword123!"

    user_id = signup_and_verify_email(email, password)

    first_login = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )

    second_login = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )

    assert first_login.status_code == 200
    assert second_login.status_code == 200

    first_token = first_login.json()["access_token"]
    second_token = second_login.json()["access_token"]

    first_claims = decode_token(first_token)
    second_claims = decode_token(second_token)

    assert first_claims["sid"] != second_claims["sid"]
    assert first_claims["jti"] != second_claims["jti"]

    with SessionLocal() as db:
        sessions = list(
            db.scalars(
                select(UserSession).where(
                    UserSession.user_id == user_id,
                )
            )
        )

        assert len(sessions) == 2

    logout_response = client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {first_token}"},
    )

    assert logout_response.status_code == 200

    first_me = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {first_token}"},
    )

    second_me = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {second_token}"},
    )

    assert first_me.status_code == 401
    assert second_me.status_code == 200


def test_expired_persistent_session_is_rejected():
    email = unique_email()
    password = "StrongPassword123!"

    user_id = signup_and_verify_email(email, password)

    login_response = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )

    assert login_response.status_code == 200

    token = login_response.json()["access_token"]
    claims = decode_token(token)

    with SessionLocal() as db:
        session = db.get(UserSession, claims["sid"])

        assert session is not None
        assert session.user_id == user_id

        session.expires_at = datetime.now(timezone.utc) - timedelta(
            seconds=1
        )
        db.commit()

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == (
        "Authenticated session has expired."
    )

def test_otp_login_creates_persistent_session(monkeypatch):
    email = unique_email()
    password = "StrongPassword123!"

    user_id = signup_and_verify_email(email, password)

    request_response = client.post(
        "/api/auth/login/otp/request",
        json={
            "email": email,
        },
    )

    assert request_response.status_code == 202

    with SessionLocal() as db:
        from src.db.models import UserVerificationCode

        verification_code = db.scalar(
            select(UserVerificationCode).where(
                UserVerificationCode.user_id == user_id,
                UserVerificationCode.channel == "email",
                UserVerificationCode.purpose == "login",
                UserVerificationCode.verified_at.is_(None),
            )
        )

        assert verification_code is not None

        from src.security.otp import hash_otp

        otp = "123456"
        verification_code.code_hash = hash_otp(otp)
        db.commit()

    verify_response = client.post(
        "/api/auth/login/otp/verify",
        json={
            "email": email,
            "code": otp,
        },
    )

    assert verify_response.status_code == 200

    access_token = verify_response.json()["access_token"]
    claims = decode_token(access_token)

    assert claims["sub"] == str(user_id)
    assert isinstance(claims["sid"], str)
    assert claims["sid"]
    assert isinstance(claims["jti"], str)
    assert claims["jti"]

    with SessionLocal() as db:
        session = db.get(UserSession, claims["sid"])

        assert session is not None
        assert session.user_id == user_id
        assert session.access_token_jti == claims["jti"]
        assert session.revoked_at is None
        assert session.expires_at > datetime.now(timezone.utc)
