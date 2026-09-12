from __future__ import annotations

import threading
import time
from typing import Any

from sqlalchemy import text

from src.db.database import SessionLocal


# Readiness is commonly polled by load balancers/orchestrators. The database
# check is remote, so cache the result briefly to avoid turning health polling
# into continuous database traffic.
READINESS_CACHE_TTL_SECONDS = 5.0

_readiness_lock = threading.Lock()
_cached_database: dict[str, Any] | None = None
_cached_at = 0.0


def check_database() -> dict[str, Any]:
    """Check whether the application database is reachable."""

    try:
        db = SessionLocal()

        try:
            db.execute(text("SELECT 1"))

            return {
                "status": "ok",
            }

        finally:
            db.close()

    except Exception as exc:
        return {
            "status": "error",
            "error_type": type(exc).__name__,
        }


def _get_cached_database_check() -> dict[str, Any]:
    """Return a short-lived cached database readiness result."""

    global _cached_database, _cached_at

    now = time.monotonic()

    with _readiness_lock:
        if (
            _cached_database is not None
            and now - _cached_at < READINESS_CACHE_TTL_SECONDS
        ):
            return dict(_cached_database)

        database = check_database()
        _cached_database = dict(database)
        _cached_at = time.monotonic()

        return database


def reset_readiness_cache() -> None:
    """Clear the readiness cache.

    Primarily useful for deterministic tests and controlled operational
    invalidation.
    """

    global _cached_database, _cached_at

    with _readiness_lock:
        _cached_database = None
        _cached_at = 0.0


def get_readiness() -> dict[str, Any]:
    """Return application readiness without calling external AI services."""

    database = _get_cached_database_check()

    ready = database["status"] == "ok"

    return {
        "status": "ready" if ready else "not_ready",
        "checks": {
            "database": database,
        },
    }
