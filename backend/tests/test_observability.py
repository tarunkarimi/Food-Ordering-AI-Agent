import logging
import json

from fastapi.testclient import TestClient

from src.main import app
from src.observability.logging import (
    Timer,
    get_request_id,
    log_event,
    new_request_id,
    set_request_id,
)


def test_request_id_is_generated_and_returned():
    client = TestClient(app)

    response = client.get(
        "/health",
    )

    assert response.status_code == 200

    request_id = response.headers.get(
        "X-Request-ID"
    )

    assert request_id
    assert len(request_id) == 32


def test_request_id_header_is_propagated():
    client = TestClient(app)

    request_id = "observability-test-123"

    response = client.get(
        "/health",
        headers={
            "X-Request-ID": request_id,
        },
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == request_id


def test_request_id_context_is_available():
    request_id = new_request_id()

    set_request_id(request_id)

    assert get_request_id() == request_id


def test_structured_log_contains_request_id(caplog):
    request_id = "logging-test-456"

    set_request_id(request_id)

    logger = logging.getLogger(
        "observability-test"
    )

    with caplog.at_level(logging.INFO):
        log_event(
            logger,
            "test_event",
            component="testing",
        )

    payload = json.loads(
        caplog.records[-1].message
    )

    assert payload["event"] == "test_event"
    assert payload["request_id"] == request_id
    assert payload["component"] == "testing"


def test_timer_returns_non_negative_elapsed_time():
    timer = Timer()

    assert timer.elapsed_ms >= 0
