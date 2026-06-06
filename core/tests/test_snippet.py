"""GET /snippet — template substitution and validation."""

from __future__ import annotations

import uuid


def test_snippet_substitutes_all_placeholders(client, monkeypatch):
    monkeypatch.setenv("RATEXP_SUBMIT_URL", "http://example.test/feedback")
    # SUBMIT_URL is read at module import — reload so the new value is picked up.
    import importlib

    import server

    importlib.reload(server)
    from fastapi.testclient import TestClient

    c = TestClient(server.app)
    r = c.get("/snippet", params={"session_id": "sess-xyz", "request_id": "req-123"})
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
    body = c.get("/snippet").text
    for key in ("session_id", "request_id"):
        marker = f'"{key}='
        start = body.index(marker) + len(marker)
        value = body[start : body.index('"', start)]
        uuid.UUID(value)  # raises if not a valid UUID


def test_snippet_rejects_invalid_agent_when_supplied(client):
    c, _ = client
    r = c.get("/snippet", params={"agent": "bad/agent"})
    assert r.status_code == 400
    assert "invalid agent" in r.json()["detail"]


def test_snippet_accepts_valid_agent(client):
    # A well-formed agent passes validation; the prompt still carries <AGENT>
    # for the model to fill from its own identity.
    c, _ = client
    r = c.get("/snippet", params={"agent": "claude-code claude-opus-4-8"})
    assert r.status_code == 200
    assert "<AGENT>" in r.text
