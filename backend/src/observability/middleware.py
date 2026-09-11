from __future__ import annotations

import logging

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from src.observability.logging import (
    Timer,
    log_event,
    new_request_id,
    reset_request_id,
    set_request_id,
)
from src.observability.metrics import (
    get_ai_metrics_summary,
    metrics,
)


logger = logging.getLogger("src.observability.http")


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Attach request IDs, structured request logs, and metrics."""

    async def dispatch(self, request: Request, call_next):
        request_id = (
            request.headers.get("X-Request-ID")
            or new_request_id()
        )

        set_request_id(request_id)
        timer = Timer()

        if request.url.path == "/metrics":
            response = JSONResponse(
                {
                    "status": "ok",
                    "metrics": metrics.snapshot(),
                    "ai": get_ai_metrics_summary(),
                }
            )

            response.headers["X-Request-ID"] = request_id
            response.headers["Cache-Control"] = "no-store"

            reset_request_id()
            return response

        try:
            response = await call_next(request)

            duration_ms = timer.elapsed_ms

            log_event(
                logger,
                "http_request_completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )

            response.headers["X-Request-ID"] = request_id

            return response

        except Exception as exc:
            duration_ms = timer.elapsed_ms

            log_event(
                logger,
                "http_request_failed",
                level=logging.ERROR,
                method=request.method,
                path=request.url.path,
                duration_ms=duration_ms,
                error_type=type(exc).__name__,
            )

            raise

        finally:
            reset_request_id()
