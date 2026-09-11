from __future__ import annotations

import json
import logging

from src.observability.logging import (
    get_request_id,
    log_event,
    reset_request_id,
    set_request_id,
)
from src.observability.metrics import metrics


class CaptureLogger:
    def __init__(self) -> None:
        self.message = None

    def log(self, level, message):
        self.message = message


def setup_function() -> None:
    metrics.reset()
    reset_request_id()


def teardown_function() -> None:
    metrics.reset()
    reset_request_id()


def test_sensitive_observability_fields_are_removed():
    logger = CaptureLogger()

    set_request_id("hardening-001")

    log_event(
        logger,
        "agent_tool_completed",
        tool_name="checkout",
        duration_ms=12.5,
        password="SECRET_PASSWORD",
        token="SECRET_TOKEN",
        authorization="Bearer SECRET",
        otp="123456",
        user_message="secret customer message",
        prompt="secret prompt",
        result="secret tool result",
    )

    assert logger.message is not None

    payload = json.loads(logger.message)

    assert payload["event"] == "agent_tool_completed"
    assert payload["request_id"] == "hardening-001"
    assert payload["tool_name"] == "checkout"
    assert payload["duration_ms"] == 12.5

    serialized = logger.message.lower()

    assert "secret_password" not in serialized
    assert "secret_token" not in serialized
    assert "bearer secret" not in serialized
    assert "123456" not in serialized
    assert "secret customer message" not in serialized
    assert "secret prompt" not in serialized
    assert "secret tool result" not in serialized


def test_error_metrics_are_classified():
    logger = logging.getLogger("test.observability")

    log_event(
        logger,
        "agent_tool_failed",
        tool_name="checkout",
        duration_ms=25.0,
        error_type="TimeoutError",
    )

    snapshot = metrics.snapshot()

    assert snapshot["counters"][
        "observability_failures_total"
    ] == 1

    assert snapshot["counters"][
        "agent_tool_errors_total"
    ] == 1

    assert snapshot["counters"][
        "agent_tool_errors.TimeoutError"
    ] == 1


def test_agent_invocation_errors_are_classified():
    logger = logging.getLogger("test.observability")

    log_event(
        logger,
        "agent_invocation_failed",
        duration_ms=31.0,
        error_type="RuntimeError",
    )

    snapshot = metrics.snapshot()

    assert snapshot["counters"][
        "agent_invocation_errors_total"
    ] == 1

    assert snapshot["counters"][
        "agent_invocation_errors.RuntimeError"
    ] == 1


def test_http_errors_are_classified():
    logger = logging.getLogger("test.observability")

    log_event(
        logger,
        "http_request_failed",
        duration_ms=5.0,
        error_type="ValueError",
    )

    snapshot = metrics.snapshot()

    assert snapshot["counters"][
        "http_errors_total"
    ] == 1

    assert snapshot["counters"][
        "http_errors.ValueError"
    ] == 1


def test_request_context_can_be_cleared():
    set_request_id("temporary-request")

    assert get_request_id() == "temporary-request"

    reset_request_id()

    assert get_request_id() == "-"
