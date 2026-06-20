"""submit_feedback MCP tool + ingest_feedback - validation and default filling."""

from __future__ import annotations

import uuid

import ingest
import mcp_app
import pytest
from models import Feedback
from pydantic import ValidationError


def _kwargs(**overrides):
    base = {
        "skill_name": "demo",
        "agent": "claude-code",
        "session_id": "sess-1",
        "request_id": "req-1",
        "score": 1,
        "comment": "great",
    }
    base.update(overrides)
    return base


def test_submit_feedback_happy(store_stub):
    assert mcp_app.submit_feedback(**_kwargs()) == "stored"
    assert len(store_stub) == 1
    assert store_stub[0].skill_name == "demo"
    assert store_stub[0].score == 1


def test_submit_feedback_score_and_comment_optional(store_stub):
    mcp_app.submit_feedback(**_kwargs(score=None, comment=None))
    assert store_stub[-1].score is None
    assert store_stub[-1].comment is None


def test_submit_feedback_score_out_of_range_rejected(store_stub):
    with pytest.raises(ValidationError):
        mcp_app.submit_feedback(**_kwargs(score=0))
    with pytest.raises(ValidationError):
        mcp_app.submit_feedback(**_kwargs(score=3))


def test_submit_feedback_request_id_propagated(store_stub):
    mcp_app.submit_feedback(**_kwargs(request_id="req-abc"))
    assert store_stub[-1].request_id == "req-abc"


def test_ingest_feedback_autofills_ids_and_created_at(store_stub):
    # The tool always passes ids, but ingest still fills them if blank.
    ingest.ingest_feedback(Feedback(skill_name="demo", agent="claude-code"))
    rec = store_stub[-1]
    uuid.UUID(rec.session_id)  # server-generated UUID
    uuid.UUID(rec.request_id)
    assert rec.created_at.endswith("Z")


def test_ingest_feedback_created_at_preserved(store_stub):
    ingest.ingest_feedback(
        Feedback(skill_name="demo", agent="claude-code", created_at="2026-01-01T00:00:00Z")
    )
    assert store_stub[-1].created_at == "2026-01-01T00:00:00Z"


def test_ingest_feedback_store_failure_propagates(monkeypatch):
    import store

    class Boom:
        def append(self, record):
            raise RuntimeError("kaboom")

        def append_transcript(self, record):
            raise RuntimeError("kaboom")

        def close(self):
            pass

    monkeypatch.setattr(store, "_store", Boom())
    with pytest.raises(RuntimeError):
        ingest.ingest_feedback(Feedback(skill_name="demo", agent="claude-code"))
