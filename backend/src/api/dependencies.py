"""FastAPI authentication dependencies."""

from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.database import get_db
from src.db.models import User, UserSession
from src.security.jwt import decode_access_token, decode_access_token_claims


_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class AuthenticatedSession:
    """Authenticated user together with the persistent session."""

    user: User
    session: UserSession


def _get_bearer_credentials(
    credentials: HTTPAuthorizationCredentials | None,
) -> str:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return credentials.credentials


def get_current_session(
    credentials: HTTPAuthorizationCredentials | None = Depends(
        _bearer_scheme
    ),
    db: Session = Depends(get_db),
) -> AuthenticatedSession:
    """Authenticate a session-bound access token."""

    token = _get_bearer_credentials(credentials)

    try:
        claims = decode_access_token_claims(token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    subject = claims.get("sub")
    session_id = claims.get("sid")
    jti = claims.get("jti")

    if (
        not isinstance(subject, str)
        or not subject.isdigit()
        or int(subject) <= 0
        or not isinstance(session_id, str)
        or not session_id
        or not isinstance(jti, str)
        or not jti
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session-bound access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = int(subject)

    user_session = db.scalar(
        select(UserSession).where(
            UserSession.id == session_id,
            UserSession.user_id == user_id,
            UserSession.access_token_jti == jti,
        )
    )

    if user_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated session no longer exists.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    now = datetime.now(timezone.utc)

    if user_session.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated session has been revoked.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user_session.expires_at <= now:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated session has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.get(User, user_id)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user no longer exists.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive.",
        )

    return AuthenticatedSession(
        user=user,
        session=user_session,
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(
        _bearer_scheme
    ),
    db: Session = Depends(get_db),
) -> User:
    """Return the authenticated user.

    Session-bound tokens are validated against persistent sessions.
    Legacy tokens without session claims remain supported temporarily
    for backwards compatibility with existing callers.
    """

    token = _get_bearer_credentials(credentials)

    try:
        claims = decode_access_token_claims(token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    has_session_claims = (
        isinstance(claims.get("sid"), str)
        and isinstance(claims.get("jti"), str)
    )

    if has_session_claims:
        authenticated_session = get_current_session(
            credentials=credentials,
            db=db,
        )
        return authenticated_session.user

    try:
        user_id = decode_access_token(token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = db.get(User, user_id)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user no longer exists.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive.",
        )

    return user
