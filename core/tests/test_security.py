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
    # Declare a content-length above the configured cap. The middleware rejects
    # it before routing, so any POST path (here the feedback endpoint) triggers it.
    monkeypatch.setattr(server, "MAX_BODY_BYTES", 10)
    r = c.post("/feedback", json={"way": "too long for the cap"})
    assert r.status_code == 413


def test_malformed_multipart_body_rejected(client):
    """A body that claims to be multipart but isn't must not reach the parser raw.

    The form parser raises on truncated or garbled parts; unhandled that is a 500
    with a traceback on a public endpoint, so it is reported as a bad body instead.
    """
    c, captured = client
    for path in ("/feedback", "/transcript"):
        r = c.post(
            path,
            content=b"garbage",
            headers={"content-type": "multipart/form-data; boundary=zz"},
        )
        assert r.status_code == 422, (path, r.status_code)
    assert captured == []


def _stream(total: int, chunk: int = 4096):
    """Yield `total` bytes piecemeal; sent chunked, i.e. with no Content-Length."""
    for _ in range(total // chunk):
        yield b"x" * chunk


def test_chunked_oversized_body_rejected(client, monkeypatch):
    import server

    c, captured = client
    # A chunked body declares no length, so the header check has nothing to look at
    # and the cap has to hold on the bytes actually read.
    monkeypatch.setattr(server, "MAX_BODY_BYTES", 1024)
    r = c.post(
        "/feedback", content=_stream(64 * 1024), headers={"content-type": "application/json"}
    )
    assert r.request.headers.get("content-length") is None  # nothing declared to catch
    assert r.status_code == 413
    assert captured == []  # never reached a destination


def test_oversized_body_stops_being_read_at_the_cap(monkeypatch):
    """The body is refused as soon as it passes the cap, not buffered to the end.

    Driven as a raw ASGI call because a test client always hands over a whole body;
    here the request keeps offering more, and the count says how much was taken.
    """
    import anyio
    import server

    monkeypatch.setattr(server, "MAX_BODY_BYTES", 1024)
    monkeypatch.setattr(server, "_limiter", RateLimiter(0))
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": "/feedback",
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("1.2.3.4", 5000),
        "headers": [(b"host", b"testserver"), (b"content-type", b"application/json")],
    }
    pulls = 0

    async def receive() -> dict:
        nonlocal pulls
        pulls += 1
        return {"type": "http.request", "body": b"x" * 512, "more_body": pulls < 64}

    sent: list[dict] = []

    async def send(message: dict) -> None:
        sent.append(message)

    anyio.run(server.app, scope, receive, send)
    assert sent[0]["status"] == 413
    assert pulls < 10  # stopped just past the 1 KiB cap, not at the 32 KiB on offer


def test_chunked_body_within_cap_reaches_the_route(client):
    # The middleware reads the body itself, so it must pass it on untouched.
    c, captured = client
    body = b'{"skill_name": "demo", "agent": "claude-code", "score": 1, "comment": "ok"}'
    r = c.post(
        "/feedback",
        content=iter([body[:30], body[30:]]),
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 201
    assert captured[-1].comment == "ok"


def test_rate_limited_request_returns_429(client, monkeypatch):
    import server

    c, _ = client
    monkeypatch.setattr(server, "_limiter", RateLimiter(per_minute=1))
    assert c.get("/healthz").status_code == 200
    assert c.get("/healthz").status_code == 429
