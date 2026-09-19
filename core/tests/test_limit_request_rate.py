"""The per-caller token bucket, on its own.

How the middleware uses it (the 429) is in test_serve_http.py.
"""

from __future__ import annotations

from api import limit_request_rate
from api.limit_request_rate import RateLimiter


def test_a_caller_is_blocked_once_its_budget_is_spent():
    limiter = RateLimiter(per_minute=2)
    assert limiter.allow("ip") is True
    assert limiter.allow("ip") is True
    assert limiter.allow("ip") is False


def test_each_caller_has_its_own_budget():
    limiter = RateLimiter(per_minute=1)
    assert limiter.allow("a") is True
    assert limiter.allow("b") is True  # a different caller, its own bucket
    assert limiter.allow("a") is False


def test_zero_disables_the_limiter():
    # config.yaml documents 0 as the off switch, so it must not mean "block all".
    limiter = RateLimiter(per_minute=0)
    assert all(limiter.allow("ip") for _ in range(100))


def test_a_spent_budget_refills_as_time_passes(monkeypatch):
    """Without this, a caller that hits the limit once is blocked for good.

    The clock is faked rather than slept through, so the test stays instant.
    """
    now = 1000.0
    monkeypatch.setattr(limit_request_rate.time, "monotonic", lambda: now)

    # per_minute is both the budget and the bucket size, so 1 spends in one
    # request and takes the whole minute to earn back.
    limiter = RateLimiter(per_minute=1)
    assert limiter.allow("ip") is True
    assert limiter.allow("ip") is False

    now += 60.0
    assert limiter.allow("ip") is True
