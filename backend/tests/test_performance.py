from concurrent.futures import ThreadPoolExecutor
from statistics import mean
import time

from fastapi.testclient import TestClient

from src.main import app
import src.observability.health as health


client = TestClient(app)


def _latency_ms(callable_, iterations: int = 10) -> list[float]:
    latencies = []

    for _ in range(iterations):
        start = time.perf_counter()
        response = callable_()
        elapsed = (time.perf_counter() - start) * 1000

        assert response.status_code == 200
        latencies.append(elapsed)

    return latencies


def test_health_endpoint_performance():
    latencies = _latency_ms(
        lambda: client.get("/health"),
        iterations=10,
    )

    average = mean(latencies)
    p95 = sorted(latencies)[int(len(latencies) * 0.95) - 1]

    assert average < 100
    assert p95 < 200


def test_metrics_endpoint_performance():
    latencies = _latency_ms(
        lambda: client.get("/metrics"),
        iterations=10,
    )

    average = mean(latencies)
    p95 = sorted(latencies)[int(len(latencies) * 0.95) - 1]

    assert average < 100
    assert p95 < 200


def test_ready_endpoint_uses_cached_database_check():
    health.reset_readiness_cache()

    first = client.get("/ready")
    assert first.status_code == 200

    latencies = _latency_ms(
        lambda: client.get("/ready"),
        iterations=10,
    )

    average = mean(latencies)
    p95 = sorted(latencies)[int(len(latencies) * 0.95) - 1]

    assert average < 100
    assert p95 < 200

    health.reset_readiness_cache()


def test_health_endpoint_handles_concurrent_requests():
    def request(_):
        response = client.get("/health")
        assert response.status_code == 200
        return response

    with ThreadPoolExecutor(max_workers=8) as executor:
        responses = list(
            executor.map(request, range(16))
        )

    assert len(responses) == 16
    assert all(
        response.json()["status"] == "ok"
        for response in responses
    )


def test_metrics_endpoint_handles_concurrent_requests():
    def request(_):
        response = client.get("/metrics")
        assert response.status_code == 200
        return response

    with ThreadPoolExecutor(max_workers=8) as executor:
        responses = list(
            executor.map(request, range(16))
        )

    assert len(responses) == 16
    assert all(
        response.json()["status"] == "ok"
        for response in responses
    )
