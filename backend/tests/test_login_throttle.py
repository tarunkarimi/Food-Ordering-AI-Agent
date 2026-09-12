from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from src.db.database import SessionLocal
from src.db.models.login_attempt import LoginAttempt
from src.db.models.user import User
from src.security.passwords import hash_password
from src.services.login_throttle import (
    MAX_FAILED_ATTEMPTS,
    is_login_locked,
    record_failed_login,
    reset_login_failures,
)


def _get_db():
    return SessionLocal()


def _create_user(db):
    user = User(
        email=f"throttle-test-{uuid4().hex}@example.com",
        password_hash=hash_password("TestPassword123!"),
        email_verified=True,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_failed_logins_increment():
    db = _get_db()
    try:
        user = _create_user(db)

        assert record_failed_login(
            db,
            user_id=user.id,
        ) is False

        attempt = db.scalar(
            select(LoginAttempt).where(LoginAttempt.user_id == user.id)
        )

        assert attempt is not None
        assert attempt.failed_attempts == 1
        assert attempt.locked_until is None
    finally:
        db.close()


def test_max_failed_logins_lock_account():
    db = _get_db()
    try:
        user = _create_user(db)

        for _ in range(MAX_FAILED_ATTEMPTS - 1):
            assert record_failed_login(
                db,
                user_id=user.id,
            ) is False

        assert record_failed_login(
            db,
            user_id=user.id,
        ) is True

        attempt = db.scalar(
            select(LoginAttempt).where(LoginAttempt.user_id == user.id)
        )

        assert attempt is not None
        assert attempt.failed_attempts == MAX_FAILED_ATTEMPTS
        assert attempt.locked_until is not None
        assert attempt.locked_until > datetime.now(timezone.utc)

        assert is_login_locked(
            db,
            user_id=user.id,
        ) is True
    finally:
        db.close()


def test_expired_lockout_resets():
    db = _get_db()
    try:
        user = _create_user(db)

        now = datetime.now(timezone.utc)

        attempt = LoginAttempt(
            user_id=user.id,
            failed_attempts=MAX_FAILED_ATTEMPTS,
            locked_until=now - timedelta(minutes=1),
            last_failed_at=now - timedelta(minutes=16),
        )
        db.add(attempt)
        db.commit()

        assert is_login_locked(
            db,
            user_id=user.id,
            now=now,
        ) is False

        db.refresh(attempt)

        assert attempt.failed_attempts == 0
        assert attempt.locked_until is None
        assert attempt.last_failed_at is None
    finally:
        db.close()


def test_successful_login_resets_failures():
    db = _get_db()
    try:
        user = _create_user(db)

        for _ in range(3):
            record_failed_login(
                db,
                user_id=user.id,
            )

        attempt = db.scalar(
            select(LoginAttempt).where(LoginAttempt.user_id == user.id)
        )

        assert attempt is not None
        assert attempt.failed_attempts == 3

        reset_login_failures(
            db,
            user_id=user.id,
        )

        db.refresh(attempt)

        assert attempt.failed_attempts == 0
        assert attempt.locked_until is None
        assert attempt.last_failed_at is None
    finally:
        db.close()


def test_untracked_user_is_not_locked():
    db = _get_db()
    try:
        user = _create_user(db)

        assert is_login_locked(
            db,
            user_id=user.id,
        ) is False
    finally:
        db.close()


