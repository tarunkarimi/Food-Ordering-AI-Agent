"""Password hashing and verification utilities."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


_password_hasher = PasswordHasher()

# Valid Argon2id hash used only to perform the same expensive verification
# path when the requested account does not exist.
DUMMY_PASSWORD_HASH = "$argon2id$v=19$m=65536,t=3,p=4$miGpGTcNnMiQ5cnE3x0CKQ$OmFboeYEt6R35juO511FqNP/TiBd3UORF2yX7/5eTjw"


def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2id."""

    if not password:
        raise ValueError("Password cannot be empty.")

    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against an Argon2id hash."""

    if not password or not password_hash:
        return False

    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
