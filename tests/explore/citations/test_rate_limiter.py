"""Deterministic timing tests for AsyncRateLimiter."""

from __future__ import annotations

import asyncio
import time

import pytest

from src.explore.citations.rate_limiter import AsyncRateLimiter


async def test_first_burst_within_capacity_is_immediate():
    """rate=2: first 2 acquisitions should both complete near-instantly."""
    limiter = AsyncRateLimiter(rate=2, period=1.0)
    start = time.monotonic()
    async with limiter:
        pass
    async with limiter:
        pass
    elapsed = time.monotonic() - start
    assert elapsed < 0.1, f"First 2 calls took {elapsed:.3f}s; expected near-instant"


async def test_third_call_waits_when_bucket_empty():
    """rate=2: after using both initial tokens, the 3rd waits ~0.5s."""
    limiter = AsyncRateLimiter(rate=2, period=1.0)
    async with limiter:
        pass
    async with limiter:
        pass
    start = time.monotonic()
    async with limiter:
        pass
    elapsed = time.monotonic() - start
    # Allow a generous margin: should be ~0.5s, but Windows timing can drift
    assert 0.3 <= elapsed <= 1.0, f"3rd call elapsed {elapsed:.3f}s; expected ~0.5s"


async def test_serialized_calls_at_rate_limit():
    """rate=4 over 4 sequential calls: total elapsed should be ~0.5s
    (first 4 instant, plus they all fit within the bucket)."""
    limiter = AsyncRateLimiter(rate=4, period=1.0)
    start = time.monotonic()
    for _ in range(4):
        async with limiter:
            pass
    elapsed = time.monotonic() - start
    assert elapsed < 0.1, f"4 calls within bucket should be near-instant; got {elapsed:.3f}s"


async def test_invalid_rate_raises():
    with pytest.raises(ValueError):
        AsyncRateLimiter(rate=0, period=1.0)
    with pytest.raises(ValueError):
        AsyncRateLimiter(rate=1, period=0)
