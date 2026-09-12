from unittest.mock import MagicMock, patch

import src.observability.health as health


def setup_function():
    health.reset_readiness_cache()


def teardown_function():
    health.reset_readiness_cache()


def test_database_check_returns_ok():
    session = MagicMock()

    with patch("src.observability.health.SessionLocal", return_value=session):
        result = health.check_database()

    assert result == {"status": "ok"}
    session.execute.assert_called_once()
    session.close.assert_called_once()


def test_database_check_hides_raw_database_error():
    session = MagicMock()
    session.execute.side_effect = RuntimeError("secret database details")

    with patch("src.observability.health.SessionLocal", return_value=session):
        result = health.check_database()

    assert result == {
        "status": "error",
        "error_type": "RuntimeError",
    }
    assert "secret database details" not in str(result)
    session.close.assert_called_once()


def test_readiness_returns_ready_when_database_is_available():
    with patch(
        "src.observability.health.check_database",
        return_value={"status": "ok"},
    ) as check:
        result = health.get_readiness()
        second = health.get_readiness()

    assert result == {
        "status": "ready",
        "checks": {
            "database": {
                "status": "ok",
            }
        },
    }
    assert second == result
    check.assert_called_once()


def test_readiness_returns_not_ready_when_database_fails():
    with patch(
        "src.observability.health.check_database",
        return_value={
            "status": "error",
            "error_type": "OperationalError",
        },
    ):
        result = health.get_readiness()

    assert result == {
        "status": "not_ready",
        "checks": {
            "database": {
                "status": "error",
                "error_type": "OperationalError",
            }
        },
    }


def test_readiness_cache_expires():
    current_time = [0.0]

    def fake_monotonic():
        return current_time[0]

    with (
        patch(
            "src.observability.health.check_database",
            side_effect=[
                {"status": "ok"},
                {"status": "error", "error_type": "OperationalError"},
            ],
        ) as check,
        patch(
            "src.observability.health.time.monotonic",
            side_effect=fake_monotonic,
        ),
    ):
        first = health.get_readiness()

        current_time[0] = 2.0
        cached = health.get_readiness()

        current_time[0] = 6.0
        expired = health.get_readiness()

    assert first["status"] == "ready"
    assert cached["status"] == "ready"
    assert expired["status"] == "not_ready"
    assert check.call_count == 2
