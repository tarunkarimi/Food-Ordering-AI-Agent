"""Authentication password policy."""

import re


MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128


def validate_password(password: str) -> str:
    """Validate a password for account creation."""

    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."
        )

    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must not exceed {MAX_PASSWORD_LENGTH} characters."
        )

    if not re.search(r"[A-Z]", password):
        raise ValueError(
            "Password must contain at least one uppercase letter."
        )

    if not re.search(r"[a-z]", password):
        raise ValueError(
            "Password must contain at least one lowercase letter."
        )

    if not re.search(r"\d", password):
        raise ValueError(
            "Password must contain at least one digit."
        )

    if not re.search(r"[^A-Za-z0-9]", password):
        raise ValueError(
            "Password must contain at least one special character."
        )

    return password
