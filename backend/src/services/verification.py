"""Verification-code delivery boundary."""

import logging

logger = logging.getLogger(__name__)


def deliver_verification_code(
    *,
    channel: str,
    destination: str,
    code: str,
) -> None:
    """Deliver a verification code through the configured channel.

    The current implementation is provider-independent. Real email/SMS
    providers can be connected here later without changing authentication
    business logic.

    The OTP is intentionally not logged or returned.
    """
    if channel not in {"email", "phone"}:
        raise ValueError("Unsupported verification channel.")

    if not destination:
        raise ValueError("Verification destination cannot be empty.")

    if not code or len(code) != 6 or not code.isdigit():
        raise ValueError("Verification code must be six digits.")

    logger.info(
        "Verification delivery pending: channel=%s",
        channel,
    )
