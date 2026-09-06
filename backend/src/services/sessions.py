"""Persistent authentication-session service."""

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from src.configs.config import config
from src.db.models import UserSession
from src.security.jwt import create_access_token


def create_user_session(
    db: Session,
    user_id: int,
) -> str:
    """Create and persist a session and return its access token."""

    session_id = secrets.token_urlsafe(32)
    jti = secrets.token_urlsafe(32)

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(
        minutes=config.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )

    access_token = create_access_token(
        user_id,
        session_id=session_id,
        jti=jti,
    )

    user_session = UserSession(
        id=session_id,
        user_id=user_id,
        access_token_jti=jti,
        created_at=now,
        expires_at=expires_at,
    )

    try:
        db.add(user_session)
        db.commit()
    except Exception:
        db.rollback()
        raise

    return access_token


def revoke_session(
    db: Session,
    user_session: UserSession,
) -> None:
    """Revoke a persistent authentication session."""

    if user_session.revoked_at is not None:
        return

    user_session.revoked_at = datetime.now(timezone.utc)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
