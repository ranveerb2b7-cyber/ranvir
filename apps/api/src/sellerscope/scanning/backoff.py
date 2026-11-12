"""Retry delays: exponential backoff with full jitter, honouring the source's Retry-After."""

from __future__ import annotations

import random
from collections.abc import Callable


def backoff_delay(
    attempt: int,
    *,
    base_s: float,
    cap_s: float,
    retry_after_s: float | None = None,
    rand: Callable[[], float] = random.random,
) -> float:
    """Delay before the next attempt, after `attempt` attempts (1-based) have failed.

    Full jitter spreads retries of many items over [0, min(cap, base * 2^(attempt-1))]. A
    source-provided Retry-After is a lower bound, never shortened.
    """
    ceiling = min(cap_s, base_s * (2 ** max(attempt - 1, 0)))
    delay = ceiling * rand()
    if retry_after_s is not None:
        delay = max(delay, retry_after_s)
    return float(min(delay, max(cap_s, retry_after_s or 0.0)))
