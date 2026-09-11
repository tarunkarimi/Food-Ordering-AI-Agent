from __future__ import annotations

import logging

from src.observability.logging import log_event
from src.observability.metrics import (
    get_ai_metrics_summary,
    metrics,
)


def setup_function() -> None:
    metrics.reset()


def teardown_function() -> None:
    metrics.reset()


def test_per_tool_latency_is_recorded():
    logger = logging.getLogger("test.metrics")

    log_event(
        logger,
        "agent_tool_started",
        tool_name="get_menu",
    )

    log_event(
        logger,
        "agent_tool_completed",
        tool_name="get_menu",
        duration_ms=20.0,
    )

    log_event(
        logger,
        "agent_tool_completed",
        tool_name="get_menu",
        duration_ms=40.0,
    )

    snapshot = metrics.snapshot()

    assert snapshot["counters"][
        "agent_tool_started.get_menu"
    ] == 1

    assert snapshot["counters"][
        "agent_tool_completed.get_menu"
    ] == 2

    duration = snapshot["durations"][
        "agent_tool_duration_ms.get_menu"
    ]

    assert duration["count"] == 2
    assert duration["total_ms"] == 60.0
    assert duration["avg_ms"] == 30.0
    assert duration["max_ms"] == 40.0


def test_ai_summary_calculates_success_and_failure_rates():
    logger = logging.getLogger("test.metrics")

    log_event(
        logger,
        "agent_invocation_started",
    )
    log_event(
        logger,
        "agent_invocation_completed",
        duration_ms=100.0,
    )

    log_event(
        logger,
        "agent_invocation_started",
    )
    log_event(
        logger,
        "agent_invocation_failed",
        duration_ms=200.0,
        error_type="RuntimeError",
    )

    log_event(
        logger,
        "agent_tool_started",
        tool_name="get_menu",
    )
    log_event(
        logger,
        "agent_tool_completed",
        tool_name="get_menu",
        duration_ms=25.0,
    )

    log_event(
        logger,
        "agent_tool_started",
        tool_name="checkout",
    )
    log_event(
        logger,
        "agent_tool_failed",
        tool_name="checkout",
        duration_ms=50.0,
        error_type="TimeoutError",
    )

    summary = get_ai_metrics_summary()

    assert summary["invocations"]["started"] == 2
    assert summary["invocations"]["completed"] == 1
    assert summary["invocations"]["failed"] == 1
    assert summary["invocations"]["success_rate"] == 0.5
    assert summary["invocations"]["failure_rate"] == 0.5

    assert summary["tools"]["started"] == 2
    assert summary["tools"]["completed"] == 1
    assert summary["tools"]["failed"] == 1
    assert summary["tools"]["success_rate"] == 0.5
    assert summary["tools"]["failure_rate"] == 0.5

    assert summary["latency"]["agent"]["count"] == 2
    assert summary["latency"]["tools"]["count"] == 2


def test_ai_summary_is_empty_when_no_ai_activity_exists():
    summary = get_ai_metrics_summary()

    assert summary["invocations"]["started"] == 0
    assert summary["invocations"]["completed"] == 0
    assert summary["invocations"]["failed"] == 0
    assert summary["invocations"]["success_rate"] is None
    assert summary["invocations"]["failure_rate"] is None

    assert summary["tools"]["started"] == 0
    assert summary["tools"]["completed"] == 0
    assert summary["tools"]["failed"] == 0


def test_metrics_do_not_store_user_payloads():
    logger = logging.getLogger("test.metrics")

    log_event(
        logger,
        "agent_tool_completed",
        tool_name="checkout",
        duration_ms=10.0,
        user_message="private customer message",
        password="secret",
        token="secret-token",
    )

    snapshot = str(metrics.snapshot())
    summary = str(get_ai_metrics_summary())

    assert "private customer message" not in snapshot
    assert "secret-token" not in snapshot
    assert "password" not in snapshot
    assert "private customer message" not in summary
    assert "secret-token" not in summary
