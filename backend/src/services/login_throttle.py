from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models.login_attempt import LoginAttempt


MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def is_login_locked(
    db: Session,
    *,
    user_id: int,
    now: datetime | None = None,
) -> bool:
    now = now or _utc_now()

    attempt = db.scalar(
        select(LoginAttempt).where(LoginAttempt.user_id == user_id)
    )

    if attempt is None:
        return False

    if attempt.locked_until is None:
        return False

    if attempt.locked_until > now:
        return True

    # Lockout expired: completely reset the throttle state.
    attempt.failed_attempts = 0
    attempt.locked_until = None
    attempt.last_failed_at = None
    db.commit()

    return False


def record_failed_login(
    db: Session,
    *,
    user_id: int,
    now: datetime | None = None,
) -> bool:
    now = now or _utc_now()

    attempt = db.scalar(
        select(LoginAttempt).where(LoginAttempt.user_id == user_id)
    )

    if attempt is None:
        attempt = LoginAttempt(
            user_id=user_id,
            failed_attempts=0,
        )
        db.add(attempt)

    attempt.failed_attempts += 1
    attempt.last_failed_at = now

    if attempt.failed_attempts >= MAX_FAILED_ATTEMPTS:
        attempt.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
        db.commit()
        return True

    db.commit()
    return False


def reset_login_failures(
    db: Session,
    *,
    user_id: int,
) -> None:
    attempt = db.scalar(
        select(LoginAttempt).where(LoginAttempt.user_id == user_id)
    )

    if attempt is None:
        return

    attempt.failed_attempts = 0
    attempt.locked_until = None
    attempt.last_failed_at = None
    db.commit()
