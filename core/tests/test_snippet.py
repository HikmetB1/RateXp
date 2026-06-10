"""GET /snippet — template substitution and validation."""

from __future__ import annotations

import re
import uuid

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def test_snippet_substitutes_all_placeholders(client, monkeypatch):
    monkeypatch.setenv("RATEXP_SUBMIT_URL", "http://example.test/feedback")
    # SUBMIT_URL is read at module import — reload so the new value is picked up.
    import importlib

    import server

    importlib.reload(server)
    from fastapi.testclient import TestClient

    c = TestClient(server.app)
    # every=1 forces the full survey prompt (default 2 would sometimes skip).
    r = c.get("/snippet", params={"session_id": "sess-xyz", "request_id": "req-123", "every": 1})
    assert r.status_code == 200
    body = r.text
    assert "http://example.test/feedback" in body
    assert "sess-xyz" in body
    assert "req-123" in body
    assert "{{" not in body  # all server-side placeholders substituted
    # skill_name and agent are AI-filled, so the snippet keeps their placeholders.
    assert "<SKILL_NAME>" in body
    assert "<AGENT>" in body


def test_snippet_generates_uuids_when_ids_omitted(client):
    c, _ = client
    # every=1 forces the full survey prompt (default 2 would sometimes skip).
    body = c.get("/snippet", params={"every": 1}).text
    # With ids omitted the server fills the session_id and request_id placeholders
    # with freshly generated UUIDs — the only UUIDs in the snippet. Both must be
    # present and valid (and distinct).
    found = set(_UUID_RE.findall(body))
    for value in found:
        uuid.UUID(value)  # raises if not a valid UUID
    assert len(found) >= 2


def test_snippet_rejects_invalid_agent_when_supplied(client):
    c, _ = client
    r = c.get("/snippet", params={"agent": "bad/agent"})
    assert r.status_code == 400
    assert "invalid agent" in r.json()["detail"]


def test_snippet_accepts_valid_agent(client):
    # A well-formed agent passes validation; the prompt still carries <AGENT>
    # for the model to fill from its own identity.
    c, _ = client
    r = c.get("/snippet", params={"agent": "claude-code claude-opus-4-8", "every": 1})
    assert r.status_code == 200
    assert "<AGENT>" in r.text


def test_snippet_default_every_from_config(client, monkeypatch):
    # With no `every` param the server samples using config's default_survey_every:
    # the dice is rolled over that range.
    import server

    seen = []
    monkeypatch.setattr(server.random, "randrange", lambda n: seen.append(n) or 0)
    c, _ = client
    c.get("/snippet")
    assert seen == [server.DEFAULT_SURVEY_EVERY]


def test_snippet_every_one_always_surveys(client):
    # every=1 wins every roll, so the full survey prompt is always returned.
    c, _ = client
    for _ in range(20):
        assert "AskUserQuestion" in c.get("/snippet", params={"every": 1}).text


def test_snippet_rejects_every_below_one(client):
    c, _ = client
    assert c.get("/snippet", params={"every": 0}).status_code == 422


def test_snippet_every_can_return_skip(client, monkeypatch):
    # On a "miss" the server returns the short skip message instead of the survey.
    import server

    monkeypatch.setattr(server.random, "randrange", lambda _n: 1)
    c, _ = client
    body = c.get("/snippet", params={"every": 5}).text
    assert "no survey this time" in body.lower()
    assert "Was this helpful?" not in body


def test_snippet_every_win_returns_survey(client, monkeypatch):
    # On a "win" (roll == 0) the normal survey prompt is returned.
    import server

    monkeypatch.setattr(server.random, "randrange", lambda _n: 0)
    c, _ = client
    assert "AskUserQuestion" in c.get("/snippet", params={"every": 5}).text
