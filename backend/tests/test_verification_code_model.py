"""Verification code database model tests."""

from datetime import datetime, timedelta, timezone

from src.db.models import UserVerificationCode


def test_verification_code_model_fields() -> None:
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=10
    )

    verification_code = UserVerificationCode(
        user_id=1,
        channel="email",
        purpose="signup",
        code_hash="$argon2id$example",
        expires_at=expires_at,
        attempts=0,
    )

    assert verification_code.user_id == 1
    assert verification_code.channel == "email"
    assert verification_code.purpose == "signup"
    assert verification_code.code_hash == "$argon2id$example"
    assert verification_code.expires_at == expires_at
    assert verification_code.verified_at is None
    assert verification_code.attempts == 0


def test_verification_code_supports_phone_channel() -> None:
    verification_code = UserVerificationCode(
        user_id=1,
        channel="phone",
        purpose="signup",
        code_hash="$argon2id$example",
        expires_at=datetime.now(timezone.utc),
    )

    assert verification_code.channel == "phone"
    assert verification_code.verified_at is None