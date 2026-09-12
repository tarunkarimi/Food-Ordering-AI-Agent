from unittest.mock import patch

import requests

from src.services.http_resilience import request_read_with_retry


def test_read_request_succeeds_without_retry():
    request = lambda: "ok"

    with patch("src.services.http_resilience.time.sleep") as sleep:
        result = request_read_with_retry(request)

    assert result == "ok"
    sleep.assert_not_called()


def test_read_request_retries_connection_error():
    calls = {"count": 0}

    def request():
        calls["count"] += 1

        if calls["count"] == 1:
            raise requests.ConnectionError("temporary failure")

        return "ok"

    with patch("src.services.http_resilience.time.sleep") as sleep:
        result = request_read_with_retry(request)

    assert result == "ok"
    assert calls["count"] == 2
    sleep.assert_called_once_with(0.1)


def test_read_request_does_not_retry_after_limit():
    request = lambda: (_ for _ in ()).throw(
        requests.Timeout("timeout")
    )

    with patch("src.services.http_resilience.time.sleep") as sleep:
        try:
            request_read_with_retry(request)
        except requests.Timeout:
            pass
        else:
            raise AssertionError("Timeout should have been raised")

    sleep.assert_called_once_with(0.1)
