"""Provision the deterministic E2E authentication account."""

from pathlib import Path
import os
import sys

# Make the backend project root importable when this file is executed directly.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.configs.config import config
from src.db_test_safety import resolve_test_database_url


E2E_EMAIL = "e2e-playwright@example.com"
E2E_PASSWORD = "E2EPassword123!"


def main() -> None:
    test_database_url = resolve_test_database_url(
        test_database_url=os.environ.get("TEST_DATABASE_URL"),
        test_database_name=os.environ.get("TEST_DATABASE_NAME"),
        confirmation=os.environ.get("TEST_DATABASE_CONFIRMATION"),
        application_database_url=config.DATABASE_URL,
        ci_environment=os.environ.get("CI", "").casefold() == "true",
    )

    # Import the ORM model only after the explicit target has passed the
    # fail-closed configuration check. This session factory is bound directly
    # to TEST_DATABASE_URL and never falls back to the application database.
    from src.db.models import User
    from src.security.passwords import hash_password
    from src.services.login_throttle import reset_login_failures

    test_engine = create_engine(test_database_url, pool_pre_ping=True)
    TestSessionLocal = sessionmaker(
        bind=test_engine,
        autoflush=False,
        autocommit=False,
    )

    try:
        with TestSessionLocal() as db:
            user = db.scalar(
                select(User).where(User.email == E2E_EMAIL)
            )

            if user is None:
                user = User(
                    email=E2E_EMAIL,
                    phone=None,
                    password_hash=hash_password(E2E_PASSWORD),
                    email_verified=True,
                    phone_verified=False,
                    is_active=True,
                )
                db.add(user)
            else:
                user.password_hash = hash_password(E2E_PASSWORD)
                user.email_verified = True
                user.phone_verified = False
                user.is_active = True

            db.commit()
            db.refresh(user)

            reset_login_failures(db, user_id=user.id)

            print(
                "E2E account ready in the explicitly verified test database."
            )
    finally:
        test_engine.dispose()


if __name__ == "__main__":
    main()
