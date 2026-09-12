"""Persistent OTP abuse-prevention policy."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db.models import UserVerificationCode


OTP_RESEND_COOLDOWN_SECONDS = 60
OTP_MAX_REQUESTS_PER_HOUR = 5


class OTPRateLimitError(ValueError):
    """Raised when OTP generation is rate limited."""


def enforce_otp_request_limits(
    db: Session,
    *,
    user_id: int,
    channel: str,
    purpose: str,
    now: datetime | None = None,
) -> None:
    """Enforce persistent cooldown and hourly OTP request limits."""

    current_time = now or datetime.now(timezone.utc)

    latest = db.scalar(
        select(UserVerificationCode)
        .where(
            UserVerificationCode.user_id == user_id,
            UserVerificationCode.channel == channel,
            UserVerificationCode.purpose == purpose,
        )
        .order_by(
            UserVerificationCode.created_at.desc(),
            UserVerificationCode.id.desc(),
        )
    )

    if latest is not None:
        latest_created_at = latest.created_at

        if latest_created_at.tzinfo is None:
            latest_created_at = latest_created_at.replace(
                tzinfo=timezone.utc
            )

        elapsed = (
            current_time - latest_created_at
        ).total_seconds()

        if elapsed < OTP_RESEND_COOLDOWN_SECONDS:
            remaining = max(
                1,
                int(
                    OTP_RESEND_COOLDOWN_SECONDS - elapsed
                ),
            )
            raise OTPRateLimitError(
                f"Please wait {remaining} seconds before requesting "
                "another verification code."
            )

    window_start = current_time - timedelta(hours=1)

    request_count = db.scalar(
        select(func.count(UserVerificationCode.id)).where(
            UserVerificationCode.user_id == user_id,
            UserVerificationCode.channel == channel,
            UserVerificationCode.purpose == purpose,
            UserVerificationCode.created_at >= window_start,
        )
    ) or 0

    if request_count >= OTP_MAX_REQUESTS_PER_HOUR:
        raise OTPRateLimitError(
            "Too many verification code requests. "
            "Please try again later."
        )
