"""Security middleware: rate limiting, body-size cap, response headers."""

from __future__ import annotations

from ratelimit import RateLimiter


def test_ratelimiter_blocks_after_capacity():
    limiter = RateLimiter(per_minute=2)
    assert limiter.allow("ip") is True
    assert limiter.allow("ip") is True
    assert limiter.allow("ip") is False  # budget exhausted


def test_ratelimiter_is_per_key():
    limiter = RateLimiter(per_minute=1)
    assert limiter.allow("a") is True
    assert limiter.allow("b") is True  # different caller, own bucket
    assert limiter.allow("a") is False


def test_ratelimiter_zero_disables():
    limiter = RateLimiter(per_minute=0)
    assert all(limiter.allow("ip") for _ in range(100))


def test_response_has_security_headers(client):
    c, _ = client
    r = c.get("/healthz")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "no-referrer"


def test_oversized_body_rejected(client, monkeypatch):
    import server

    c, _ = client
    # Declare a content-length above the configured cap.
    monkeypatch.setattr(server, "MAX_BODY_BYTES", 10)
    r = c.post("/feedback", json={"skill_name": "x", "agent": "y", "comment": "way too long"})
    assert r.status_code == 413


def test_rate_limited_request_returns_429(client, monkeypatch):
    import server

    c, _ = client
    monkeypatch.setattr(server, "_limiter", RateLimiter(per_minute=1))
    assert c.get("/healthz").status_code == 200
    assert c.get("/healthz").status_code == 429
