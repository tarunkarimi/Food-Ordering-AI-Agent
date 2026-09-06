"""OTP generation, hashing, and verification utilities."""

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import (
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)


OTP_LENGTH = 6

_otp_hasher = PasswordHasher()


def generate_otp() -> str:
    """Generate a cryptographically secure six-digit OTP."""
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(otp: str) -> str:
    """Hash an OTP before storing it."""
    if not otp or len(otp) != OTP_LENGTH or not otp.isdigit():
        raise ValueError("OTP must be a six-digit numeric code.")

    return _otp_hasher.hash(otp)


def verify_otp(otp: str, otp_hash: str) -> bool:
    """Verify an OTP against its stored hash."""
    if not otp or not otp_hash:
        return False

    if len(otp) != OTP_LENGTH or not otp.isdigit():
        return False

    try:
        return _otp_hasher.verify(otp_hash, otp)
    except (
        VerifyMismatchError,
        VerificationError,
        InvalidHashError,
    ):
        return False