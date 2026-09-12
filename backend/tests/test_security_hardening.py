from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient

from src.configs.config import config
from src.main import app
from src.security.jwt import ALGORITHM, create_access_token


client = TestClient(app)


def test_config_requires_strong_jwt_secret():
    assert len(config.JWT_SECRET_KEY) >= 32


def test_sessionless_token_is_rejected_by_authenticated_dependency():
    from src.api.dependencies import get_current_user

    token = create_access_token(123)

    credentials = MagicMock()
    credentials.scheme = "Bearer"
    credentials.credentials = token

    db = MagicMock()

    with pytest.raises(Exception) as exc_info:
        get_current_user(
            credentials=credentials,
            db=db,
        )

    assert "session-bound" in str(exc_info.value).lower()


def test_security_headers_are_present():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert (
        response.headers["Referrer-Policy"]
        == "strict-origin-when-cross-origin"
    )
    assert "frame-ancestors 'none'" in (
        response.headers["Content-Security-Policy"]
    )
    assert "object-src 'none'" in (
        response.headers["Content-Security-Policy"]
    )


def test_cors_allows_configured_frontend_origin():
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert (
        response.headers["Access-Control-Allow-Origin"]
        == "http://localhost:5173"
    )


def test_cors_rejects_unconfigured_origin():
    response = client.options(
        "/health",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_jwt_algorithm_is_fixed():
    assert ALGORITHM == "HS256"


def test_expired_sessionless_token_is_not_accepted():
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

    from src.security.jwt import decode_access_token_claims

    with pytest.raises(ValueError, match="Invalid or expired"):
        decode_access_token_claims(token)
