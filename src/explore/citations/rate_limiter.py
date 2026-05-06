"""AsyncRateLimiter — token bucket for HTTP rate limiting.

Used by SemanticScholarProvider since the public SS endpoint enforces
1 req/s without API key (much higher with key). Token bucket gives smooth
burst-then-pace behavior rather than rigid sleep-after-each-request.

Per docs/onboard-redesign/11-citation-provider.md.
"""

from __future__ import annotations

import asyncio
import time


class AsyncRateLimiter:
    """Token bucket: rate tokens per period seconds, refilled continuously.

    Acquire one token via `async with limiter:`. Sleeps until a token is
    available if the bucket is empty.

    Note: bucket capacity = rate (i.e. allows rate-burst).
    """

    def __init__(self, rate: float, period: float = 1.0):
        if rate <= 0 or period <= 0:
            raise ValueError("rate and period must be positive")
        self.rate = rate
        self.period = period
        self._tokens = float(rate)  # start full
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def __aenter__(self):
        async with self._lock:
            now = time.monotonic()
            # Refill tokens proportional to elapsed time, capped at rate.
            elapsed = now - self._last_refill
            self._tokens = min(self.rate, self._tokens + elapsed * self.rate / self.period)
            self._last_refill = now

            if self._tokens >= 1:
                self._tokens -= 1
                return self

            # Bucket empty: sleep until one token refills.
            wait = (1 - self._tokens) * self.period / self.rate
            # Release the lock during sleep so other waiters can refill check too.
        # Sleeping outside the lock — when we wake, take the token directly
        # (don't re-enter the refill path or other waiters will all race).
        await asyncio.sleep(wait)
        async with self._lock:
            self._tokens = max(0.0, self._tokens - 1)  # account for our take
            self._last_refill = time.monotonic()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None
