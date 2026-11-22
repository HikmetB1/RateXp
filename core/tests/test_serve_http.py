"""The parts of the HTTP surface that are not the two POST routes.

The security middleware, the health check, and the settings the plugin's hooks ask for.
`client` and `captured_writes` come from conftest.py.
"""

from __future__ import annotations

import json

from api import serve_http
from api.limit_request_rate import RateLimiter
from load_config import Eval

JSON_CT = {"content-type": "application/json"}


def test_healthz_reports_ok(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_every_response_carries_the_security_headers(client):
    headers = client.get("/healthz").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "no-referrer"


def test_a_declared_content_length_over_the_cap_is_refused(client, monkeypatch):
    # Cheap path: the header says how big it is, so nothing has to be read.
    monkeypatch.setattr(serve_http, "MAX_BODY_BYTES", 10)
    assert client.post("/feedback", json={"way": "too long for the cap"}).status_code == 413


def _stream(total: int, chunk: int = 4096):
    """Yield `total` bytes piecemeal, which httpx sends chunked, with no length."""
    for _ in range(total // chunk):
        yield b"x" * chunk


def test_a_chunked_body_over_the_cap_is_refused(client, captured_writes, monkeypatch):
    # A chunked body declares no length, so the header check has nothing to look
    # at and the cap has to hold on the bytes actually read.
    monkeypatch.setattr(serve_http, "MAX_BODY_BYTES", 1024)
    response = client.post("/feedback", content=_stream(64 * 1024), headers=JSON_CT)
    assert response.request.headers.get("content-length") is None
    assert response.status_code == 413
    assert captured_writes == []


def test_an_oversized_body_stops_being_read_at_the_cap(monkeypatch):
    """Refused as soon as it passes the cap, not buffered to the end.

    Driven as a raw ASGI call because a test client always hands over a whole
    body. Here the request keeps offering more, and the pull count says how much
    was taken before the middleware gave up.
    """
    import anyio

    monkeypatch.setattr(serve_http, "MAX_BODY_BYTES", 1024)
    monkeypatch.setattr(serve_http, "_limiter", RateLimiter(0))
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

    anyio.run(serve_http.app, scope, receive, send)
    assert sent[0]["status"] == 413
    assert pulls < 10  # stopped just past the 1 KiB cap, not at the 32 KiB on offer


def test_a_chunked_body_within_the_cap_reaches_the_route_intact(client, captured_writes):
    # The middleware reads the body itself to meter it, so it has to replay it.
    body = b'{"skill_name": "demo", "agent": "claude-code", "score": 1, "comment": "ok"}'
    response = client.post("/feedback", content=iter([body[:30], body[30:]]), headers=JSON_CT)
    assert response.status_code == 201
    assert captured_writes[-1].comment == "ok"


def test_a_body_claiming_to_be_multipart_but_isnt_is_refused(client, captured_writes):
    # The form parser raises on truncated or garbled parts. Unhandled, that is a
    # 500 with a traceback on a public endpoint.
    for path in ("/feedback", "/transcript"):
        response = client.post(
            path, content=b"garbage", headers={"content-type": "multipart/form-data; boundary=zz"}
        )
        assert response.status_code == 422, path
    assert captured_writes == []


def test_a_caller_over_its_budget_gets_429(client, monkeypatch):
    monkeypatch.setattr(serve_http, "_limiter", RateLimiter(per_minute=1))
    assert client.get("/healthz").status_code == 200
    assert client.get("/healthz").status_code == 429


def test_core_serves_no_hook_script_and_no_installer(client):
    # The plugin brings the hooks, so nothing here hands out a script to run.
    for path in ("/ratexp-claude.sh", "/ratexp-cursor.sh", "/install.sh"):
        assert client.get(path).status_code == 404


def test_hook_settings_carry_the_configured_surveys_and_turns(client):
    # The plugin's hooks ask for these at session start.
    from load_config import DEFAULT_SURVEY_EVAL, DEFAULT_SURVEY_EVERY, EVALS

    body = client.get("/hook-settings").json()
    assert body["every"] == DEFAULT_SURVEY_EVERY
    assert body["default_eval"] == DEFAULT_SURVEY_EVAL
    assert body["evals"] == [{"name": name, **survey._asdict()} for name, survey in EVALS.items()]


def test_hook_settings_carry_the_evals_exactly_as_written(client, monkeypatch):
    # An admin writes the wording, so quotes, $(...) and backticks in it reach the
    # hooks as plain text.
    tricky = Eval(
        'It\'s {subject} "done"? $(touch ran) `touch ran` \\o/', "Up", "Yes.", "Down", "$HOME"
    )
    monkeypatch.setattr(serve_http, "EVALS", {"tricky": tricky})
    monkeypatch.setattr(serve_http, "DEFAULT_SURVEY_EVAL", "tricky")
    body = client.get("/hook-settings").json()
    assert body["default_eval"] == "tricky"
    assert body["evals"] == [{"name": "tricky", **tricky._asdict()}]


def test_hook_settings_name_the_version_in_the_plugin_manifest(client):
    manifest = json.loads(serve_http.PLUGIN_MANIFEST.read_text(encoding="utf-8"))
    assert client.get("/hook-settings").json()["plugin_version"] == manifest["version"]
