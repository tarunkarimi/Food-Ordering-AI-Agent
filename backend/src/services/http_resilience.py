from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

import requests

from src.configs.config import config


T = TypeVar("T")


def request_read_with_retry(
    request: Callable[[], T],
) -> T:
    """
    Execute a read-only downstream request with bounded retry behavior.

    This helper is intentionally limited to idempotent/read operations.
    Mutating operations such as checkout and cancellation must not use it.
    """

    attempts = config.DOWNSTREAM_READ_RETRIES + 1

    for attempt in range(attempts):
        try:
            return request()

        except (
            requests.Timeout,
            requests.ConnectionError,
        ):
            if attempt >= attempts - 1:
                raise

            # Small bounded backoff.
            time.sleep(0.1 * (attempt + 1))

    raise RuntimeError("Read request failed unexpectedly.")
