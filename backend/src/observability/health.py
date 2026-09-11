from __future__ import annotations

from typing import Any

from sqlalchemy import text

from src.db.database import SessionLocal


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


def get_readiness() -> dict[str, Any]:
    """Return application readiness without calling external AI services."""

    database = check_database()

    ready = database["status"] == "ok"

    return {
        "status": "ready" if ready else "not_ready",
        "checks": {
            "database": database,
        },
    }

