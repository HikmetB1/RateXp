"""submit_trajectory MCP tool + ingest_transcript - convert, size-limit, redact, store."""

from __future__ import annotations

import json

import ingest
import mcp_app
import pytest

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


def _kwargs(**overrides):
    base = {
        "skill_name": "goodbye",
        "agent": "claude-code claude-opus-4-8",
        "session_id": "sess-1",
        "request_id": "req-1",
        "transcript": RAW_JSONL,
    }
    base.update(overrides)
    return base


def test_submit_trajectory_from_raw_jsonl(store_stub):
    assert mcp_app.submit_trajectory(**_kwargs()) == "stored"
    rec = store_stub[-1]
    assert rec.skill_name == "goodbye"
    assert rec.request_id == "req-1"
    assert rec.schema_version == "ATIF-v1.7"
    assert rec.atif["session_id"] == "sess-1"
    assert [s["source"] for s in rec.atif["steps"]] == ["user", "agent"]


def test_submit_trajectory_from_prebuilt_atif(store_stub):
    mcp_app.submit_trajectory(
        skill_name="cheerful",
        agent="claude-code",
        session_id="sess-9",
        request_id="req-9",
        atif={"schema_version": "ATIF-v1.7", "steps": []},
    )
    assert store_stub[-1].atif == {"schema_version": "ATIF-v1.7", "steps": []}


def test_submit_trajectory_requires_transcript_or_atif(store_stub):
    with pytest.raises(ValueError):
        mcp_app.submit_trajectory(skill_name="x", agent="y", session_id="s", request_id="r")


def test_submit_trajectory_empty_transcript_rejected(store_stub):
    with pytest.raises(ValueError):
        mcp_app.submit_trajectory(**_kwargs(transcript="   "))


def test_transcript_created_at_autofilled(store_stub):
    mcp_app.submit_trajectory(**_kwargs())
    assert store_stub[-1].created_at.endswith("Z")


def test_transcript_redaction_applied_before_store(store_stub, monkeypatch):
    monkeypatch.setattr(ingest, "redact_atif", lambda atif: {**atif, "redacted": True})
    mcp_app.submit_trajectory(**_kwargs())
    assert store_stub[-1].atif.get("redacted") is True


def test_transcript_oversized_stored_as_stub(store_stub, monkeypatch):
    # Shrink the limit so a normal transcript counts as oversized.
    monkeypatch.setattr(ingest, "MAX_TRANSCRIPT_BYTES", 10)
    # Redaction must be skipped for the meta-only stub - blow up if it's reached.
    monkeypatch.setattr(
        ingest, "redact_atif", lambda atif: (_ for _ in ()).throw(AssertionError("redacted"))
    )
    mcp_app.submit_trajectory(**_kwargs())
    atif = store_stub[-1].atif
    assert atif["steps"] == []  # bulky trajectory dropped
    assert atif["oversized"]["limit_bytes"] == 10
    assert atif["oversized"]["byte_size"] > 10
    assert "final_metrics" in atif  # token/step totals kept


def test_transcript_small_stored_in_full(store_stub):
    mcp_app.submit_trajectory(**_kwargs())
    atif = store_stub[-1].atif
    assert "oversized" not in atif  # under the limit -> full trajectory kept
    assert [s["source"] for s in atif["steps"]] == ["user", "agent"]


def test_transcript_redaction_failure_propagates(store_stub, monkeypatch):
    def boom(_atif):
        raise RuntimeError("azure down")

    monkeypatch.setattr(ingest, "redact_atif", boom)
    with pytest.raises(RuntimeError):
        mcp_app.submit_trajectory(**_kwargs())


# --- HTTP POST /transcript: the direct-upload path the shell helper uses -------


def test_http_transcript_form_happy(client):
    c, captured = client
    r = c.post(
        "/transcript",
        data={
            "session_id": "sess-1",
            "request_id": "req-1",
            "agent": "claude-code claude-opus-4-8",
            "skill_name": "goodbye",
            "transcript": RAW_JSONL,
        },
    )
    assert r.status_code == 201
    assert r.json() == {"status": "stored"}
    rec = captured[-1]
    assert rec.skill_name == "goodbye"
    assert rec.request_id == "req-1"
    assert [s["source"] for s in rec.atif["steps"]] == ["user", "agent"]


def test_http_transcript_empty_rejected(client):
    c, _ = client
    assert c.post("/transcript", data={"transcript": "   "}).status_code == 422


def test_http_transcript_json_atif_body(client):
    c, captured = client
    r = c.post(
        "/transcript",
        json={
            "session_id": "s9",
            "skill_name": "cheerful",
            "agent": "claude-code",
            "atif": {"schema_version": "ATIF-v1.7", "steps": []},
            "request_id": "r9",
        },
    )
    assert r.status_code == 201
    assert captured[-1].atif == {"schema_version": "ATIF-v1.7", "steps": []}


def test_upload_transcript_sh_is_served(client):
    c, _ = client
    r = c.get("/upload_transcript.sh")
    assert r.status_code == 200
    assert "transcript@" in r.text  # uploads the file with curl's @ syntax
