"""POST /feedback + ingest_feedback - validation, default filling, fan-out failure."""

from __future__ import annotations

import uuid

import ingest
import pytest
from models import Feedback

# The hook posts every field with `curl --form-string`, i.e. multipart form data.
FORM = {
    "skill_name": "demo",
    "agent": "claude-code",
    "session_id": "sess-1",
    "request_id": "req-1",
    "score": "1",
    "comment": "great",
}


def _multipart(**overrides) -> dict:
    """FORM plus overrides as httpx multipart fields; an override of None drops it."""
    fields = {**FORM, **overrides}
    return {name: (None, value) for name, value in fields.items() if value is not None}


class _Boom:
    """A destination that always fails."""

    name = "boom"

    def write_feedback(self, record):
        raise RuntimeError("kaboom")

    def write_transcript(self, record):
        raise RuntimeError("kaboom")

    def close(self):
        pass


def test_http_feedback_form_happy(client):
    c, captured = client
    r = c.post("/feedback", files=_multipart())
    assert r.status_code == 201
    assert r.json() == {"status": "stored"}
    rec = captured[-1]
    assert rec.skill_name == "demo"
    assert rec.agent == "claude-code"
    assert rec.score == 1  # "1" on the wire, coerced to int
    assert rec.comment == "great"


def test_http_feedback_json_happy(client):
    c, captured = client
    r = c.post("/feedback", json={**FORM, "score": 1})
    assert r.status_code == 201
    assert r.json() == {"status": "stored"}
    assert captured[-1].score == 1
    assert captured[-1].comment == "great"


def test_http_feedback_score_and_comment_optional(client):
    c, captured = client
    r = c.post(
        "/feedback",
        json={"skill_name": "demo", "agent": "claude-code", "score": None, "comment": None},
    )
    assert r.status_code == 201
    assert captured[-1].score is None
    assert captured[-1].comment is None


def test_http_feedback_form_without_score(client):
    # Picker dismissed without a rating: the hook leaves both fields out entirely.
    c, captured = client
    r = c.post("/feedback", files=_multipart(score=None, comment=None))
    assert r.status_code == 201
    assert captured[-1].score is None
    assert captured[-1].comment is None


def test_http_feedback_score_out_of_range_rejected(client):
    c, captured = client
    assert c.post("/feedback", files=_multipart(score="0")).status_code == 422
    assert c.post("/feedback", json={**FORM, "score": 3}).status_code == 422
    assert c.post("/feedback", files=_multipart(score="maybe")).status_code == 422
    assert captured == []  # nothing reached a destination


def test_http_feedback_score_must_be_plain_ascii_digits(client):
    # These pass str.isdigit(), but int() either refuses them outright or would
    # record a rating the user never gave.
    c, captured = client
    assert c.post("/feedback", files=_multipart(score="٢")).status_code == 422  # Arabic-Indic
    assert c.post("/feedback", files=_multipart(score="²")).status_code == 422  # superscript
    assert c.post("/feedback", files=_multipart(score="1" * 100_000)).status_code == 422
    assert captured == []


def test_http_feedback_unreadable_body_rejected(client):
    # A public endpoint is posted every shape there is; none of them is a crash.
    c, captured = client
    plain = {"content-type": "text/plain"}
    json_ct = {"content-type": "application/json"}
    assert c.post("/feedback", content=b"not json at all", headers=plain).status_code == 422
    assert c.post("/feedback", content=b"[" * 50_000, headers=json_ct).status_code == 422
    assert c.post("/feedback", content=b"\xff\xfe", headers=json_ct).status_code == 422
    assert captured == []


def test_http_feedback_json_root_must_be_an_object(client):
    # A list, string, number or null root carries no fields to build a rating from.
    c, captured = client
    for body in (b"[1, 2]", b'"hi"', b"42", b"null"):
        r = c.post("/feedback", content=body, headers={"content-type": "application/json"})
        assert r.status_code == 422, body
    assert captured == []


def test_http_feedback_file_part_is_not_a_text_field(client):
    # curl -F 'comment=@/etc/hostname' sends a file where text belongs. The part is
    # dropped, so the rating stores exactly as if no comment had been given.
    c, captured = client
    r = c.post("/feedback", files={**_multipart(comment=None), "comment": ("host", b"secret")})
    assert r.status_code == 201
    assert captured[-1].comment is None


def test_http_feedback_request_id_propagated(client):
    c, captured = client
    c.post("/feedback", files=_multipart(request_id="req-abc"))
    assert captured[-1].request_id == "req-abc"


def test_http_feedback_no_destination_returns_503(client, monkeypatch):
    import dispatch

    c, _ = client
    monkeypatch.setattr(dispatch, "_adapters", [_Boom()])
    assert c.post("/feedback", files=_multipart()).status_code == 503


def test_ingest_feedback_autofills_ids_and_created_at(store_stub):
    # The hook always sends ids, but ingest still fills them if blank.
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


def test_ingest_feedback_all_destinations_failing_raises(monkeypatch):
    # Fan-out is at-least-one: with no destination accepting the record, the
    # caller must hear about it (server.py turns this into HTTP 503).
    import dispatch

    monkeypatch.setattr(dispatch, "_adapters", [_Boom()])
    with pytest.raises(dispatch.WriteError):
        ingest.ingest_feedback(Feedback(skill_name="demo", agent="claude-code"))
