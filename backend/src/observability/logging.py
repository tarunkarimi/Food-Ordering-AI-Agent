from __future__ import annotations

import json
import logging
import time
import uuid
from contextvars import ContextVar
from typing import Any

from src.observability.metrics import record_observability_event


_request_id: ContextVar[str] = ContextVar("request_id", default="-")


_SENSITIVE_FIELD_NAMES = {
    "password",
    "passwd",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "cookie",
    "set_cookie",
    "otp",
    "otp_code",
    "verification_code",
    "api_key",
    "apikey",
    "jwt",
    "user_message",
    "prompt",
    "response",
    "content",
    "messages",
    "tool_args",
    "arguments",
    "result",
}


def new_request_id() -> str:
    """Create a compact request identifier."""

    return uuid.uuid4().hex


def set_request_id(request_id: str) -> None:
    _request_id.set(request_id)


def reset_request_id() -> None:
    """Clear request-scoped request ID context."""

    _request_id.set("-")


def get_request_id() -> str:
    return _request_id.get()


def _sanitize_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Remove sensitive fields before structured logging."""

    sanitized: dict[str, Any] = {}

    for key, value in fields.items():
        normalized_key = str(key).strip().lower()

        if normalized_key in _SENSITIVE_FIELD_NAMES:
            continue

        sanitized[key] = value

    return sanitized


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """Emit a structured JSON event with sensitive fields removed."""

    safe_fields = _sanitize_fields(fields)

    request_id = get_request_id()

    duration_ms = safe_fields.get("duration_ms")
    tool_name = safe_fields.get("tool_name")

    record_observability_event(
        event,
        duration_ms=(
            duration_ms
            if isinstance(duration_ms, (int, float))
            else None
        ),
        tool_name=tool_name if isinstance(tool_name, str) else None,
        error_type=(
            safe_fields.get("error_type")
            if isinstance(safe_fields.get("error_type"), str)
            else None
        ),
    )

    payload = {
        "event": event,
        "request_id": request_id,
        **safe_fields,
    }

    logger.log(
        level,
        json.dumps(
            payload,
            separators=(",", ":"),
            default=str,
        ),
    )


class Timer:
    """Monotonic timer for duration measurements."""

    def __init__(self) -> None:
        self._started = time.monotonic()

    @property
    def elapsed_ms(self) -> float:
        return round(
            (time.monotonic() - self._started) * 1000,
            2,
        )
