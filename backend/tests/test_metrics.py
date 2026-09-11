from __future__ import annotations

from src.observability.logging import log_event
from src.observability.metrics import MetricsRegistry, metrics


def setup_function() -> None:
    metrics.reset()


def teardown_function() -> None:
    metrics.reset()


def test_metrics_registry_counts_and_aggregates_durations():
    registry = MetricsRegistry()

    registry.increment("requests")
    registry.increment("requests")
    registry.observe_duration("request_duration_ms", 10)
    registry.observe_duration("request_duration_ms", 30)

    snapshot = registry.snapshot()

    assert snapshot["counters"]["requests"] == 2
    assert snapshot["durations"]["request_duration_ms"]["count"] == 2
    assert snapshot["durations"]["request_duration_ms"]["total_ms"] == 40.0
    assert snapshot["durations"]["request_duration_ms"]["avg_ms"] == 20.0
    assert snapshot["durations"]["request_duration_ms"]["max_ms"] == 30.0


def test_agent_events_are_aggregated_without_payloads():
    class DummyLogger:
        def log(self, level, message):
            self.message = message

    logger = DummyLogger()

    log_event(
        logger,
        "agent_tool_completed",
        tool_name="get_menu",
        duration_ms=15.5,
        secret_should_never_be_logged="super-secret",
    )

    snapshot = metrics.snapshot()

    assert snapshot["counters"]["agent_tools_completed_total"] == 1
    assert snapshot["counters"]["agent_tool_completed.get_menu"] == 1
    assert snapshot["durations"]["agent_tool_duration_ms"]["count"] == 1
    assert snapshot["durations"]["agent_tool_duration_ms"]["total_ms"] == 15.5


def test_agent_failures_are_aggregated():
    log_event(
        __import__("logging").getLogger("test"),
        "agent_invocation_failed",
        duration_ms=42.0,
        error_type="RuntimeError",
    )

    log_event(
        __import__("logging").getLogger("test"),
        "agent_tool_failed",
        tool_name="checkout",
        duration_ms=8.0,
        error_type="TimeoutError",
    )

    snapshot = metrics.snapshot()

    assert snapshot["counters"]["agent_invocations_failed_total"] == 1
    assert snapshot["counters"]["agent_tools_failed_total"] == 1
    assert snapshot["counters"]["agent_tool_failed.checkout"] == 1


def test_metrics_snapshot_does_not_contain_sensitive_payload():
    log_event(
        __import__("logging").getLogger("test"),
        "agent_tool_completed",
        tool_name="checkout",
        duration_ms=10,
        password="DO_NOT_STORE",
        token="DO_NOT_STORE",
        user_message="DO_NOT_STORE",
    )

    snapshot = str(metrics.snapshot())

    assert "DO_NOT_STORE" not in snapshot
    assert "password" not in snapshot
    assert "token" not in snapshot
    assert "user_message" not in snapshot
