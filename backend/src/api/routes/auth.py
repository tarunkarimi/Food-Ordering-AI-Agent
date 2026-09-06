"""Authentication routes."""

import logging
from datetime import datetime, timedelta, timezone

import phonenumbers
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    model_validator,
)
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.db.database import get_db
from src.db.models import User, UserVerificationCode
from src.security.otp import generate_otp, hash_otp, verify_otp
from src.security.passwords import hash_password


logger = logging.getLogger(__name__)

router = APIRouter()


OTP_EXPIRY_MINUTES = 10
MAX_OTP_ATTEMPTS = 5


def normalize_email(email: str) -> str:
    """Normalize an email address."""
    return email.strip().lower()


def normalize_phone(phone: str) -> str:
    """Normalize a phone number to E.164 format."""
    value = phone.strip()

    if not value:
        raise ValueError("Phone number cannot be empty.")

    try:
        parsed = phonenumbers.parse(value, None)
    except phonenumbers.NumberParseException as exc:
        raise ValueError("Invalid phone number.") from exc

    if not phonenumbers.is_valid_number(parsed):
        raise ValueError("Invalid phone number.")

    return phonenumbers.format_number(
        parsed,
        phonenumbers.PhoneNumberFormat.E164,
    )


class SignupRequest(BaseModel):
    """Signup request."""

    email: EmailStr | None = None

    phone: str | None = Field(
        default=None,
        min_length=7,
        max_length=32,
    )

    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_identity(self) -> "SignupRequest":
        if self.email is None and not self.phone:
            raise ValueError(
                "Either email or phone is required."
            )

        if self.email is not None and self.phone:
            raise ValueError(
                "Provide either email or phone, not both."
            )

        return self


class SignupResponse(BaseModel):
    """Signup response."""

    id: int
    email: EmailStr | None
    phone: str | None
    email_verified: bool
    phone_verified: bool
    is_active: bool


class VerificationRequest(BaseModel):
    """Request to generate a verification code."""

    user_id: int = Field(gt=0)

    channel: str = Field(
        ...,
        pattern="^(email|phone)$",
    )

    purpose: str = Field(
        default="signup",
        pattern="^signup$",
    )


class VerificationResponse(BaseModel):
    """Verification request response."""

    message: str


class VerifyOTPRequest(BaseModel):
    """OTP verification request."""

    user_id: int = Field(gt=0)

    channel: str = Field(
        ...,
        pattern="^(email|phone)$",
    )

    purpose: str = Field(
        default="signup",
        pattern="^signup$",
    )

    code: str = Field(
        ...,
        min_length=6,
        max_length=6,
        pattern=r"^\d{6}$",
    )


class VerifyOTPResponse(BaseModel):
    """OTP verification response."""

    message: str
    verified: bool


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_201_CREATED,
)
def signup(
    request: SignupRequest,
    db: Session = Depends(get_db),
) -> SignupResponse:
    """Create an unverified user account."""

    email = (
        normalize_email(str(request.email))
        if request.email
        else None
    )

    phone = None

    if request.phone:
        try:
            phone = normalize_phone(request.phone)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

    identity_filters = []

    if email is not None:
        identity_filters.append(User.email == email)

    if phone is not None:
        identity_filters.append(User.phone == phone)

    existing_user = db.scalar(
        select(User).where(or_(*identity_filters))
    )

    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "An account with this email or phone "
                "already exists."
            ),
        )

    user = User(
        email=email,
        phone=phone,
        password_hash=hash_password(request.password),
        email_verified=False,
        phone_verified=False,
        is_active=True,
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    logger.info(
        "Created user account with id=%s",
        user.id,
    )

    return SignupResponse(
        id=user.id,
        email=user.email,
        phone=user.phone,
        email_verified=user.email_verified,
        phone_verified=user.phone_verified,
        is_active=user.is_active,
    )


@router.post(
    "/verification/request",
    response_model=VerificationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_verification_code(
    request: VerificationRequest,
    db: Session = Depends(get_db),
) -> VerificationResponse:
    """Generate a new signup verification code."""

    user = db.get(User, request.user_id)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive.",
        )

    if request.channel == "email":
        if user.email is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User does not have an email address.",
            )

        if user.email_verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is already verified.",
            )

    else:
        if user.phone is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User does not have a phone number.",
            )

        if user.phone_verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Phone number is already verified.",
            )

    now = datetime.now(timezone.utc)

    previous_codes = db.scalars(
        select(UserVerificationCode).where(
            UserVerificationCode.user_id == user.id,
            UserVerificationCode.channel == request.channel,
            UserVerificationCode.purpose == request.purpose,
            UserVerificationCode.verified_at.is_(None),
        )
    ).all()

    for previous_code in previous_codes:
        previous_code.verified_at = now

    otp = generate_otp()

    verification_code = UserVerificationCode(
        user_id=user.id,
        channel=request.channel,
        purpose=request.purpose,
        code_hash=hash_otp(otp),
        expires_at=now
        + timedelta(minutes=OTP_EXPIRY_MINUTES),
        attempts=0,
    )

    db.add(verification_code)
    db.commit()

    # Delivery provider integration will be added later.
    # Never return the OTP from the production API.
    logger.info(
        "Created %s verification code for user_id=%s",
        request.channel,
        user.id,
    )

    return VerificationResponse(
        message=(
            "Verification code generated. "
            "Delivery provider integration is pending."
        ),
    )


@router.post(
    "/verification/verify",
    response_model=VerifyOTPResponse,
)
def verify_verification_code(
    request: VerifyOTPRequest,
    db: Session = Depends(get_db),
) -> VerifyOTPResponse:
    """Verify a signup OTP."""

    user = db.get(User, request.user_id)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    verification_code = db.scalar(
        select(UserVerificationCode)
        .where(
            UserVerificationCode.user_id == user.id,
            UserVerificationCode.channel == request.channel,
            UserVerificationCode.purpose == request.purpose,
            UserVerificationCode.verified_at.is_(None),
        )
        .order_by(
            UserVerificationCode.created_at.desc(),
            UserVerificationCode.id.desc(),
        )
    )

    if verification_code is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active verification code found.",
        )

    now = datetime.now(timezone.utc)

    if verification_code.expires_at <= now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification code has expired.",
        )

    if verification_code.attempts >= MAX_OTP_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Maximum verification attempts exceeded.",
        )

    verification_code.attempts += 1

    if not verify_otp(
        request.code,
        verification_code.code_hash,
    ):
        db.commit()

        remaining_attempts = (
            MAX_OTP_ATTEMPTS
            - verification_code.attempts
        )

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Invalid verification code. "
                f"{remaining_attempts} attempt(s) remaining."
            ),
        )

    verification_code.verified_at = now

    if request.channel == "email":
        user.email_verified = True
    else:
        user.phone_verified = True

    db.commit()

    logger.info(
        "Verified %s for user_id=%s",
        request.channel,
        user.id,
    )

    return VerifyOTPResponse(
        message="Verification successful.",
        verified=True,
    )