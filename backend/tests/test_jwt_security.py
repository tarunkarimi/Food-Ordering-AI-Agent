"""JWT security utility tests."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from src.configs.config import config
from src.security.jwt import (
    ALGORITHM,
    create_access_token,
    decode_access_token,
)


def test_create_access_token_contains_user_id() -> None:
    token = create_access_token(123)

    payload = jwt.decode(
        token,
        config.JWT_SECRET_KEY,
        algorithms=[ALGORITHM],
    )

    assert payload["sub"] == "123"
    assert "iat" in payload
    assert "exp" in payload


def test_decode_access_token_returns_user_id() -> None:
    token = create_access_token(456)

    assert decode_access_token(token) == 456


def test_decode_access_token_rejects_invalid_token() -> None:
    with pytest.raises(ValueError, match="Invalid or expired"):
        decode_access_token("not-a-valid-token")


def test_decode_access_token_rejects_wrong_secret() -> None:
    token = jwt.encode(
        {
            "sub": "123",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc)
            + timedelta(minutes=30),
        },
        "wrong-secret",
        algorithm=ALGORITHM,
    )

    with pytest.raises(ValueError, match="Invalid or expired"):
        decode_access_token(token)


def test_decode_access_token_rejects_expired_token() -> None:
    token = jwt.encode(
        {
            "sub": "123",
            "iat": datetime.now(timezone.utc)
            - timedelta(minutes=10),
            "exp": datetime.now(timezone.utc)
            - timedelta(minutes=1),
        },
        config.JWT_SECRET_KEY,
        algorithm=ALGORITHM,
    )

    with pytest.raises(ValueError, match="Invalid or expired"):
        decode_access_token(token)


def test_decode_access_token_rejects_missing_subject() -> None:
    token = jwt.encode(
        {
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc)
            + timedelta(minutes=30),
        },
        config.JWT_SECRET_KEY,
        algorithm=ALGORITHM,
    )

    with pytest.raises(ValueError, match="Invalid access token subject"):
        decode_access_token(token)


def test_decode_access_token_rejects_non_numeric_subject() -> None:
    token = jwt.encode(
        {
            "sub": "abc",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc)
            + timedelta(minutes=30),
        },
        config.JWT_SECRET_KEY,
        algorithm=ALGORITHM,
    )

    with pytest.raises(ValueError, match="Invalid access token subject"):
        decode_access_token(token)


def test_decode_access_token_rejects_zero_subject() -> None:
    token = jwt.encode(
        {
            "sub": "0",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc)
            + timedelta(minutes=30),
        },
        config.JWT_SECRET_KEY,
        algorithm=ALGORITHM,
    )

    with pytest.raises(ValueError, match="Invalid access token subject"):
        decode_access_token(token)