from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

import requests

LOGGER = logging.getLogger(__name__)

T = TypeVar("T")


def run_with_retries(
    operation: Callable[[], T],
    *,
    description: str,
    max_attempts: int,
    retry_delays_seconds: tuple[int, ...],
    logger: logging.Logger | None = None,
) -> T:
    active_logger = logger or LOGGER
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            if attempt >= max_attempts or not is_retryable_request_exception(exc):
                raise
            delay = retry_delay(retry_delays_seconds, attempt)
            active_logger.warning(
                "%s failed on attempt %s/%s: %s; retrying in %ss",
                description,
                attempt,
                max_attempts,
                exc,
                delay,
            )
            time.sleep(delay)
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"{description} failed without an explicit error")


def is_retryable_request_exception(exc: Exception) -> bool:
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return exc.response.status_code in {429, 500, 502, 503, 504}
    return False


def retry_delay(retry_delays_seconds: tuple[int, ...], attempt: int) -> int:
    index = min(attempt - 1, len(retry_delays_seconds) - 1)
    return int(retry_delays_seconds[index])
