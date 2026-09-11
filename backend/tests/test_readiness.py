from __future__ import annotations

from unittest.mock import patch

from src.observability.health import (
    check_database,
    get_readiness,
)


def test_database_check_returns_ok_when_database_is_available():
    with patch("src.observability.health.SessionLocal") as session_factory:
        db = session_factory.return_value

        result = check_database()

        assert result == {"status": "ok"}
        db.execute.assert_called_once()
        db.close.assert_called_once()


def test_database_check_returns_error_without_exposing_details():
    with patch("src.observability.health.SessionLocal") as session_factory:
        session_factory.side_effect = RuntimeError(
            "database-password=SECRET"
        )

        result = check_database()

        assert result["status"] == "error"
        assert result["error_type"] == "RuntimeError"
        assert "SECRET" not in str(result)


def test_readiness_is_ready_when_database_is_ready():
    with patch(
        "src.observability.health.check_database",
        return_value={"status": "ok"},
    ):
        result = get_readiness()

        assert result["status"] == "ready"
        assert result["checks"]["database"]["status"] == "ok"


def test_readiness_is_not_ready_when_database_fails():
    with patch(
        "src.observability.health.check_database",
        return_value={
            "status": "error",
            "error_type": "OperationalError",
        },
    ):
        result = get_readiness()

        assert result["status"] == "not_ready"
        assert (
            result["checks"]["database"]["status"]
            == "error"
        )
        assert (
            result["checks"]["database"]["error_type"]
            == "OperationalError"
        )


def test_readiness_endpoint_does_not_require_external_ai_call():
    with patch(
        "src.observability.health.check_database",
        return_value={"status": "ok"},
    ) as database_check:
        result = get_readiness()

        database_check.assert_called_once()
        assert result["status"] == "ready"

