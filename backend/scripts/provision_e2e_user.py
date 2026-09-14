"""Provision the deterministic E2E authentication account."""

from pathlib import Path
import sys

# Make the backend project root importable when this file is executed directly.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select

from src.db.database import SessionLocal
from src.db.models import User
from src.security.passwords import hash_password
from src.services.login_throttle import reset_login_failures


E2E_EMAIL = "e2e-playwright@example.com"
E2E_PASSWORD = "E2EPassword123!"


def main() -> None:
    with SessionLocal() as db:
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
            f"E2E account ready: id={user.id}, "
            f"email={user.email}, verified={user.email_verified}, "
            f"active={user.is_active}"
        )


if __name__ == "__main__":
    main()
