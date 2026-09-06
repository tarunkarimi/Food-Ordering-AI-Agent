import pytest

from src.security.passwords import hash_password, verify_password


def test_hash_password_does_not_return_plaintext():
    password = "StrongPassword123!"

    password_hash = hash_password(password)

    assert password_hash != password
    assert password_hash.startswith("$argon2id$")


def test_hash_password_generates_different_hashes():
    password = "StrongPassword123!"

    first_hash = hash_password(password)
    second_hash = hash_password(password)

    assert first_hash != second_hash


def test_verify_password_accepts_correct_password():
    password = "StrongPassword123!"
    password_hash = hash_password(password)

    assert verify_password(password, password_hash) is True


def test_verify_password_rejects_wrong_password():
    password_hash = hash_password("StrongPassword123!")

    assert verify_password("WrongPassword123!", password_hash) is False


def test_empty_password_is_rejected():
    with pytest.raises(ValueError, match="Password cannot be empty"):
        hash_password("")


def test_verify_password_handles_invalid_hash():
    assert verify_password("SomePassword123!", "not-a-valid-hash") is False