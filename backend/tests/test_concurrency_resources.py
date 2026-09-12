from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from unittest.mock import patch
import time

import pytest

from src.services.ai_concurrency import AIConcurrencyLimiter
import src.observability.health as health


def test_ai_concurrency_limit_is_positive():
    limiter = AIConcurrencyLimiter(2)

    assert limiter.limit == 2


def test_ai_concurrency_limit_rejects_invalid_value():
    with pytest.raises(ValueError):
        AIConcurrencyLimiter(0)


def test_ai_concurrency_limiter_releases_after_exception():
    limiter = AIConcurrencyLimiter(1)

    with pytest.raises(RuntimeError):
        with limiter.acquire():
            raise RuntimeError("model failure")

    # If the semaphore was not released, this would block.
    with limiter.acquire():
        pass


def test_ai_concurrency_limiter_bounds_parallel_work():
    limiter = AIConcurrencyLimiter(2)

    active = 0
    maximum_active = 0
    lock = Lock()

    def worker():
        nonlocal active, maximum_active

        with limiter.acquire():
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)

            time.sleep(0.05)

            with lock:
                active -= 1

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(worker) for _ in range(6)]

        for future in futures:
            future.result()

    assert maximum_active <= 2


def test_readiness_cache_is_safe_under_concurrent_access():
    health.reset_readiness_cache()

    with patch(
        "src.observability.health.check_database",
        return_value={"status": "ok"},
    ) as check:

        def worker(_):
            return health.get_readiness()

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(
                executor.map(worker, range(16))
            )

    assert all(result["status"] == "ready" for result in results)

    # The cache lock prevents duplicate database checks during
    # initial cache population.
    assert check.call_count == 1

    health.reset_readiness_cache()
