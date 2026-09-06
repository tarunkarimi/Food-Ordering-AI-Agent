"""OTP security utility tests."""

from src.security.otp import (
    OTP_LENGTH,
    generate_otp,
    hash_otp,
    verify_otp,
)


def test_generate_otp_has_six_digits() -> None:
    otp = generate_otp()

    assert len(otp) == OTP_LENGTH
    assert otp.isdigit()


def test_generate_otp_preserves_leading_zeroes() -> None:
    values = {generate_otp() for _ in range(1000)}

    assert all(len(value) == OTP_LENGTH for value in values)
    assert all(value.isdigit() for value in values)


def test_hash_otp_does_not_store_plaintext() -> None:
    otp = "123456"

    otp_hash = hash_otp(otp)

    assert otp_hash != otp
    assert otp_hash.startswith("$argon2")


def test_verify_otp_accepts_correct_code() -> None:
    otp = "123456"
    otp_hash = hash_otp(otp)

    assert verify_otp(otp, otp_hash) is True


def test_verify_otp_rejects_wrong_code() -> None:
    otp_hash = hash_otp("123456")

    assert verify_otp("654321", otp_hash) is False


def test_verify_otp_rejects_invalid_format() -> None:
    otp_hash = hash_otp("123456")

    assert verify_otp("12345", otp_hash) is False
    assert verify_otp("abcdef", otp_hash) is False
    assert verify_otp("", otp_hash) is False


def test_hash_otp_rejects_invalid_otp() -> None:
    invalid_values = [
        "",
        "12345",
        "1234567",
        "abcdef",
        "12a456",
    ]

    for value in invalid_values:
        try:
            hash_otp(value)
        except ValueError:
            pass
        else:
            raise AssertionError(
                "Expected ValueError for invalid OTP."
            )