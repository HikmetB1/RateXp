"""The shared write path: fill defaults, size-limit, redact, then store.

`captured_writes` and `no_destination_accepts` come from conftest.py.
"""

from __future__ import annotations

import json
import uuid

import pytest
from api import ingest_records
from api.build_trajectory import claude_jsonl_to_atif
from api.record_schemas import Feedback, Transcript
from modules.write.dispatch_to_adapters import WriteError

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


def _transcript(**overrides) -> Transcript:
    base = {
        "skill_name": "goodbye",
        "agent": "claude-code",
        "session_id": "sess-1",
        "atif": claude_jsonl_to_atif(RAW_JSONL, session_id="sess-1", agent="claude-code"),
    }
    return Transcript(**{**base, **overrides})


def test_a_rating_with_no_ids_gets_server_generated_ones(captured_writes):
    # The hook always sends ids. The seeder and other callers may not.
    ingest_records.ingest_feedback(Feedback(skill_name="demo", agent="claude-code"))
    record = captured_writes[-1]
    uuid.UUID(record.session_id)
    uuid.UUID(record.request_id)
    assert record.created_at.endswith("Z")


def test_a_supplied_created_at_is_not_overwritten(captured_writes):
    ingest_records.ingest_feedback(
        Feedback(skill_name="demo", agent="claude-code", created_at="2026-01-01T00:00:00Z")
    )
    assert captured_writes[-1].created_at == "2026-01-01T00:00:00Z"


def test_a_rating_no_destination_accepted_raises(no_destination_accepts):
    # At-least-one fan-out: the caller has to hear about it, so serve_http can
    # answer 503 rather than claim the rating was stored.
    with pytest.raises(WriteError):
        ingest_records.ingest_feedback(Feedback(skill_name="demo", agent="claude-code"))


def test_a_trajectory_within_the_limit_is_stored_whole(captured_writes):
    ingest_records.ingest_transcript(_transcript())
    stored = captured_writes[-1].atif
    assert "oversized" not in stored
    assert [s["source"] for s in stored["steps"]] == ["user", "agent"]


def test_an_oversized_trajectory_is_stored_as_a_stub_without_being_redacted(
    captured_writes, monkeypatch
):
    """Size first, then redaction. The order is the point of this test.

    The stub carries no conversation text, so redacting it would pay for a
    fail-closed provider call that has nothing to mask. Redaction is replaced
    with a trap here: if the order ever flips, this fails instead of just
    getting slower and more expensive.
    """
    monkeypatch.setattr(ingest_records, "MAX_TRANSCRIPT_BYTES", 10)

    def never_called(_atif):
        raise AssertionError("the stub was handed to redaction")

    monkeypatch.setattr(ingest_records, "redact_atif", never_called)

    ingest_records.ingest_transcript(_transcript())
    stored = captured_writes[-1].atif
    assert stored["steps"] == []
    assert stored["oversized"]["limit_bytes"] == 10


def test_a_trajectory_is_redacted_before_it_is_stored(captured_writes, monkeypatch):
    monkeypatch.setattr(ingest_records, "redact_atif", lambda atif: {**atif, "masked": True})
    ingest_records.ingest_transcript(_transcript())
    assert captured_writes[-1].atif["masked"] is True


def test_a_redaction_failure_stores_nothing(captured_writes, monkeypatch):
    # Fail-closed: if masking cannot be proven to have happened, the upload is
    # dropped rather than written in the clear.
    def boom(_atif):
        raise RuntimeError("language service down")

    monkeypatch.setattr(ingest_records, "redact_atif", boom)
    with pytest.raises(RuntimeError):
        ingest_records.ingest_transcript(_transcript())
    assert captured_writes == []


def test_a_trajectory_no_destination_accepted_raises(no_destination_accepts):
    with pytest.raises(WriteError):
        ingest_records.ingest_transcript(_transcript())
