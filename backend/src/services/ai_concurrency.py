from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

from src.configs.config import config


class AIConcurrencyLimiter:
    """Bound concurrent AI model invocations within one application process."""

    def __init__(self, limit: int) -> None:
        if limit < 1:
            raise ValueError("AI concurrency limit must be at least 1.")

        self.limit = limit
        self._semaphore = threading.BoundedSemaphore(limit)

    @contextmanager
    def acquire(self) -> Iterator[None]:
        self._semaphore.acquire()

        try:
            yield
        finally:
            self._semaphore.release()


ai_concurrency_limiter = AIConcurrencyLimiter(
    config.AI_MAX_CONCURRENT_REQUESTS
)
