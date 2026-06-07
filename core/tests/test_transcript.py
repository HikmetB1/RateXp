"""POST /transcript — form upload → ATIF conversion → adapter dispatch."""

from __future__ import annotations

import json

RAW_JSONL = "\n".join(
    json.dumps(line)
    for line in [
        {"type": "user", "message": {"role": "user", "content": "hi"}},
        {
            "type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "hello"}]},
        },
    ]
)


def _form(**overrides):
    base = {
        "session_id": "sess-1",
        "request_id": "req-1",
        "agent": "claude-code claude-opus-4-8",
        "skill_name": "goodbye",
        "transcript": RAW_JSONL,
    }
    base.update(overrides)
    return base


def test_transcript_form_happy(client):
    c, captured = client
    r = c.post("/transcript", data=_form())
    assert r.status_code == 201
    assert r.json() == {"status": "stored"}
    rec = captured[-1]
    assert rec.skill_name == "goodbye"
    assert rec.request_id == "req-1"
    assert rec.schema_version == "ATIF-v1.7"
    assert rec.atif["session_id"] == "sess-1"
    assert [s["source"] for s in rec.atif["steps"]] == ["user", "agent"]


def test_transcript_created_at_autofilled(client):
    c, captured = client
    r = c.post("/transcript", data=_form())
    assert r.status_code == 201
    assert captured[-1].created_at.endswith("Z")


def test_transcript_empty_rejected(client):
    c, _ = client
    r = c.post("/transcript", data=_form(transcript="   "))
    assert r.status_code == 422


def test_transcript_json_body_with_prebuilt_atif(client):
    c, captured = client
    body = {
        "session_id": "sess-9",
        "skill_name": "cheerful",
        "agent": "claude-code",
        "atif": {"schema_version": "ATIF-v1.7", "steps": []},
        "request_id": "req-9",
    }
    r = c.post("/transcript", json=body)
    assert r.status_code == 201
    assert captured[-1].atif == {"schema_version": "ATIF-v1.7", "steps": []}


def test_transcript_store_failure_returns_503(failing_client):
    r = failing_client.post("/transcript", data=_form())
    assert r.status_code == 503
    assert "store failed" in r.json()["detail"]


def test_transcript_redaction_applied_before_store(client, monkeypatch):
    import server

    monkeypatch.setattr(server, "redact_atif", lambda atif: {**atif, "redacted": True})
    c, captured = client
    r = c.post("/transcript", data=_form())
    assert r.status_code == 201
    assert captured[-1].atif.get("redacted") is True


def test_transcript_redaction_failure_returns_502(client, monkeypatch):
    import server

    def boom(_atif):
        raise RuntimeError("azure down")

    monkeypatch.setattr(server, "redact_atif", boom)
    c, _ = client
    r = c.post("/transcript", data=_form())
    assert r.status_code == 502
    assert "redaction failed" in r.json()["detail"]
