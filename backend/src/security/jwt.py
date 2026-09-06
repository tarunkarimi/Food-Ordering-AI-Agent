"""JWT access-token utilities."""

from datetime import datetime, timedelta, timezone

import jwt

from src.configs.config import config


ALGORITHM = "HS256"


def create_access_token(
    user_id: int,
    *,
    session_id: str | None = None,
    jti: str | None = None,
) -> str:
    """Create a JWT access token.

    Session-bound tokens include both a session ID and a unique JTI.
    The optional parameters preserve compatibility with existing callers
    that create standalone tokens.
    """

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(
        minutes=config.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )

    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": expires_at,
    }

    if session_id is not None:
        payload["sid"] = session_id

    if jti is not None:
        payload["jti"] = jti

    return jwt.encode(
        payload,
        config.JWT_SECRET_KEY,
        algorithm=ALGORITHM,
    )


def decode_access_token_claims(token: str) -> dict:
    """Decode and validate a JWT access token and return its claims."""

    try:
        payload = jwt.decode(
            token,
            config.JWT_SECRET_KEY,
            algorithms=[ALGORITHM],
        )
    except jwt.PyJWTError as exc:
        raise ValueError("Invalid or expired access token.") from exc

    subject = payload.get("sub")

    if not isinstance(subject, str) or not subject.isdigit():
        raise ValueError("Invalid access token subject.")

    user_id = int(subject)

    if user_id <= 0:
        raise ValueError("Invalid access token subject.")

    return payload


def decode_access_token(token: str) -> int:
    """Decode and validate a JWT access token and return the user ID."""

    payload = decode_access_token_claims(token)

    return int(payload["sub"])
