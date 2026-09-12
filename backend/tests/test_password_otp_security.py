"""Password and OTP security policy tests."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from src.db.database import SessionLocal
from src.db.models import User, UserVerificationCode
from src.security.otp_policy import (
    OTP_MAX_REQUESTS_PER_HOUR,
    OTP_RESEND_COOLDOWN_SECONDS,
    enforce_otp_request_limits,
)
from src.security.password_policy import validate_password
from src.security.passwords import hash_password


def _unique_email() -> str:
    return f"password-otp-{uuid4().hex}@example.com"


def _create_user() -> int:
    with SessionLocal() as db:
        user = User(
            email=_unique_email(),
            phone=None,
            password_hash=hash_password("StrongPassword123!"),
            email_verified=True,
            phone_verified=False,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id


def _create_otp(
    user_id: int,
    *,
    created_at: datetime | None = None,
    index: int = 0,
) -> None:
    now = datetime.now(timezone.utc)

    with SessionLocal() as db:
        code = UserVerificationCode(
            user_id=user_id,
            channel="email",
            purpose="login",
            code_hash=f"test-hash-{uuid4().hex}-{index}",
            expires_at=now + timedelta(minutes=10),
            created_at=created_at or now,
        )
        db.add(code)
        db.commit()


def test_password_policy_accepts_strong_password() -> None:
    validate_password("StrongPassword123!")


@pytest.mark.parametrize(
    "password",
    [
        "short1!",
        "alllowercase123!",
        "ALLUPPERCASE123!",
        "NoDigitsPassword!",
        "NoSpecialCharacter123",
    ],
)
def test_password_policy_rejects_weak_password(password: str) -> None:
    with pytest.raises(ValueError):
        validate_password(password)


def test_password_policy_rejects_overlong_password() -> None:
    password = "StrongPassword123!" + ("a" * 128)

    with pytest.raises(ValueError, match="128"):
        validate_password(password)


def test_first_otp_request_is_allowed() -> None:
    user_id = _create_user()

    with SessionLocal() as db:
        enforce_otp_request_limits(
            db,
            user_id=user_id,
            channel="email",
            purpose="login",
        )


def test_otp_resend_cooldown() -> None:
    user_id = _create_user()
    _create_otp(user_id)

    with SessionLocal() as db:
        with pytest.raises(ValueError, match="5[0-9] seconds"):
            enforce_otp_request_limits(
                db,
                user_id=user_id,
                channel="email",
                purpose="login",
            )


def test_otp_request_allowed_after_cooldown() -> None:
    user_id = _create_user()

    old_time = datetime.now(timezone.utc) - timedelta(
        seconds=OTP_RESEND_COOLDOWN_SECONDS + 1
    )

    _create_otp(
        user_id,
        created_at=old_time,
    )

    with SessionLocal() as db:
        enforce_otp_request_limits(
            db,
            user_id=user_id,
            channel="email",
            purpose="login",
        )


def test_otp_hourly_request_limit() -> None:
    user_id = _create_user()
    now = datetime.now(timezone.utc)

    for index in range(OTP_MAX_REQUESTS_PER_HOUR):
        _create_otp(
            user_id,
            created_at=now - timedelta(minutes=index + 1),
            index=index,
        )

    with SessionLocal() as db:
        with pytest.raises(ValueError, match="Too many"):
            enforce_otp_request_limits(
                db,
                user_id=user_id,
                channel="email",
                purpose="login",
            )


def test_old_otp_requests_do_not_count() -> None:
    user_id = _create_user()

    old_time = datetime.now(timezone.utc) - timedelta(hours=2)

    for index in range(OTP_MAX_REQUESTS_PER_HOUR + 2):
        _create_otp(
            user_id,
            created_at=old_time,
            index=index,
        )

    with SessionLocal() as db:
        enforce_otp_request_limits(
            db,
            user_id=user_id,
            channel="email",
            purpose="login",
        )

