"""Retry helpers: exponential backoff with jitter for segment downloads."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

DEFAULT_MAX_RETRIES = 5
DEFAULT_INITIAL_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.25  # ±25 %


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff parameters."""

    max_retries: int = DEFAULT_MAX_RETRIES
    initial_delay: float = DEFAULT_INITIAL_DELAY
    max_delay: float = DEFAULT_MAX_DELAY
    jitter: float = DEFAULT_JITTER


class MaxRetriesExceededError(Exception):
    """All retries exhausted."""


def backoff_delay(attempt: int, policy: RetryPolicy) -> float:
    """Compute delay for the given attempt (1-indexed) using exp backoff + jitter."""
    base = min(policy.initial_delay * (2 ** (attempt - 1)), policy.max_delay)
    spread = base * policy.jitter
    result: float = base + random.uniform(-spread, spread)  # noqa: S311
    return result


_DEFAULT_RETRY_POLICY = RetryPolicy()


async def retry_async(
    func: Callable[[], Awaitable[object]],
    *,
    policy: RetryPolicy | None = None,
    retry_on: type[BaseException] | tuple[type[BaseException], ...] = Exception,
    on_retry: Callable[[int, BaseException, float], None] | None = None,
) -> None:
    """Call func until it succeeds or policy.max_retries is exhausted.

    `retry_on` filters which exceptions trigger a retry (others propagate immediately).
    `on_retry(attempt, exc, delay)` is called before each sleep, useful for logging.
    """
    if policy is None:
        policy = _DEFAULT_RETRY_POLICY
    last_exc: BaseException | None = None
    for attempt in range(1, policy.max_retries + 1):
        try:
            await func()
            return
        except retry_on as exc:  # noqa: PERF203
            last_exc = exc
            if attempt >= policy.max_retries:
                break
            delay = backoff_delay(attempt, policy)
            if on_retry is not None:
                on_retry(attempt, exc, delay)
            await asyncio.sleep(delay)

    assert last_exc is not None
    raise MaxRetriesExceededError(
        f"failed after {policy.max_retries} retries: {last_exc}"
    ) from last_exc
