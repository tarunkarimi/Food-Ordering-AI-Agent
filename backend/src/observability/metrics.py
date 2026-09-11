from __future__ import annotations

from collections import defaultdict
from threading import Lock
from typing import Any


class MetricsRegistry:
    """Thread-safe in-process metrics registry."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._durations: dict[str, dict[str, float | int]] = defaultdict(
            lambda: {
                "count": 0,
                "total_ms": 0.0,
                "max_ms": 0.0,
            }
        )

    def increment(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] += value

    def observe_duration(self, name: str, duration_ms: float) -> None:
        duration = max(0.0, float(duration_ms))

        with self._lock:
            bucket = self._durations[name]
            bucket["count"] = int(bucket["count"]) + 1
            bucket["total_ms"] = float(bucket["total_ms"]) + duration
            bucket["max_ms"] = max(
                float(bucket["max_ms"]),
                duration,
            )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            counters = dict(self._counters)

            durations: dict[str, dict[str, float | int]] = {}

            for name, bucket in self._durations.items():
                count = int(bucket["count"])
                total_ms = float(bucket["total_ms"])

                durations[name] = {
                    "count": count,
                    "total_ms": round(total_ms, 2),
                    "avg_ms": (
                        round(total_ms / count, 2)
                        if count
                        else 0.0
                    ),
                    "max_ms": round(
                        float(bucket["max_ms"]),
                        2,
                    ),
                }

            return {
                "counters": counters,
                "durations": durations,
            }

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._durations.clear()


metrics = MetricsRegistry()


def _record_tool_metric(
    event: str,
    tool_name: str | None,
    duration_ms: float | None,
) -> None:
    if event == "agent_tool_started":
        metrics.increment("agent_tools_started_total")

        if tool_name:
            metrics.increment(
                f"agent_tool_started.{tool_name}"
            )

    elif event == "agent_tool_completed":
        metrics.increment("agent_tools_completed_total")

        if tool_name:
            metrics.increment(
                f"agent_tool_completed.{tool_name}"
            )

        if duration_ms is not None:
            metrics.observe_duration(
                "agent_tool_duration_ms",
                duration_ms,
            )

            if tool_name:
                metrics.observe_duration(
                    f"agent_tool_duration_ms.{tool_name}",
                    duration_ms,
                )

    elif event == "agent_tool_failed":
        metrics.increment("agent_tools_failed_total")

        if tool_name:
            metrics.increment(
                f"agent_tool_failed.{tool_name}"
            )

        if duration_ms is not None:
            metrics.observe_duration(
                "agent_tool_duration_ms",
                duration_ms,
            )

            if tool_name:
                metrics.observe_duration(
                    f"agent_tool_duration_ms.{tool_name}",
                    duration_ms,
                )


def record_observability_event(
    event: str,
    *,
    duration_ms: float | None = None,
    tool_name: str | None = None,
    error_type: str | None = None,
) -> None:
    """Translate structured observability events into metrics."""

    if event == "http_request_completed":
        metrics.increment("http_requests_completed_total")

        if duration_ms is not None:
            metrics.observe_duration(
                "http_request_duration_ms",
                duration_ms,
            )

    elif event == "http_request_failed":
        metrics.increment("http_requests_failed_total")

        if duration_ms is not None:
            metrics.observe_duration(
                "http_request_duration_ms",
                duration_ms,
            )

    elif event == "agent_invocation_started":
        metrics.increment("agent_invocations_started_total")

    elif event == "agent_invocation_completed":
        metrics.increment("agent_invocations_completed_total")

        if duration_ms is not None:
            metrics.observe_duration(
                "agent_invocation_duration_ms",
                duration_ms,
            )

    elif event == "agent_invocation_failed":
        metrics.increment("agent_invocations_failed_total")

        if duration_ms is not None:
            metrics.observe_duration(
                "agent_invocation_duration_ms",
                duration_ms,
            )

    elif event in {
        "agent_tool_started",
        "agent_tool_completed",
        "agent_tool_failed",
    }:
        _record_tool_metric(
            event,
            tool_name,
            duration_ms,
        )

    if event.endswith("_failed"):
        metrics.increment("observability_failures_total")

        if event.startswith("http_request_"):
            prefix = "http_errors"
        elif event.startswith("agent_invocation_"):
            prefix = "agent_invocation_errors"
        elif event.startswith("agent_tool_"):
            prefix = "agent_tool_errors"
        else:
            prefix = None

        if prefix:
            metrics.increment(f"{prefix}_total")

            if error_type:
                metrics.increment(
                    f"{prefix}.{error_type}"
                )


def get_ai_metrics_summary() -> dict[str, Any]:
    """Return a compact AI-agent performance summary."""

    snapshot = metrics.snapshot()
    counters = snapshot["counters"]
    durations = snapshot["durations"]

    invocations_started = counters.get(
        "agent_invocations_started_total",
        0,
    )
    invocations_completed = counters.get(
        "agent_invocations_completed_total",
        0,
    )
    invocations_failed = counters.get(
        "agent_invocations_failed_total",
        0,
    )

    tools_started = counters.get(
        "agent_tools_started_total",
        0,
    )
    tools_completed = counters.get(
        "agent_tools_completed_total",
        0,
    )
    tools_failed = counters.get(
        "agent_tools_failed_total",
        0,
    )

    return {
        "invocations": {
            "started": invocations_started,
            "completed": invocations_completed,
            "failed": invocations_failed,
            "success_rate": (
                round(
                    invocations_completed
                    / invocations_started,
                    4,
                )
                if invocations_started
                else None
            ),
            "failure_rate": (
                round(
                    invocations_failed
                    / invocations_started,
                    4,
                )
                if invocations_started
                else None
            ),
        },
        "tools": {
            "started": tools_started,
            "completed": tools_completed,
            "failed": tools_failed,
            "success_rate": (
                round(
                    tools_completed
                    / tools_started,
                    4,
                )
                if tools_started
                else None
            ),
            "failure_rate": (
                round(
                    tools_failed
                    / tools_started,
                    4,
                )
                if tools_started
                else None
            ),
        },
        "latency": {
            "agent": durations.get(
                "agent_invocation_duration_ms"
            ),
            "tools": durations.get(
                "agent_tool_duration_ms"
            ),
        },
    }
