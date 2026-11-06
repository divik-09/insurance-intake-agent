"""Tiny retry-with-exponential-backoff helper (no dependency on tenacity)."""
from __future__ import annotations

import logging
import time
from typing import Callable, TypeVar

T = TypeVar("T")
log = logging.getLogger("intake.retry")


class RetryExhausted(RuntimeError):
    def __init__(self, attempts: int, last_error: Exception):
        super().__init__(f"gave up after {attempts} attempts: {last_error}")
        self.attempts = attempts
        self.last_error = last_error


def retry_call(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 0.5,
    retry_on: tuple[type[Exception], ...] = (Exception,),
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[T, int]:
    """Call `fn` until it succeeds. Returns (result, attempts_used).

    Delay doubles each time: base, 2*base, 4*base ... (no sleep after the last try).
    Exceptions not listed in `retry_on` propagate immediately — we only retry
    failures that might be transient.
    """
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn(), attempt
        except retry_on as exc:
            last = exc
            log.warning("attempt failed", extra={"attempt": attempt, "of": attempts, "error": str(exc)})
            if attempt < attempts:
                sleep(base_delay * 2 ** (attempt - 1))
    assert last is not None
    raise RetryExhausted(attempts, last)
