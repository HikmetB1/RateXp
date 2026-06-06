"""POST /feedback — validation, store dispatch, default filling."""

from __future__ import annotations

import uuid


def _payload(**overrides):
    base = {
        "session_id": "sess-1",
        "skill_name": "demo",
        "agent": "claude-code",
        "score": 1,
        "comment": "great",
    }
    base.update(overrides)
    return base


def test_healthz(client):
    c, _ = client
    r = c.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_feedback_happy(client):
    c, captured = client
    r = c.post("/feedback", json=_payload())
    assert r.status_code == 201
    assert r.json() == {"status": "stored"}
    assert len(captured) == 1
    assert captured[0].skill_name == "demo"
    assert captured[0].score == 1


def test_feedback_form_encoded_accepted(client):
    c, captured = client
    r = c.post("/feedback", data=_payload(score=2))
    assert r.status_code == 201
    assert captured[-1].score == 2


def test_feedback_form_null_strings_treated_as_missing(client):
    c, captured = client
    r = c.post("/feedback", data=_payload(score="null", comment="null"))
    assert r.status_code == 201
    assert captured[-1].score is None
    assert captured[-1].comment is None


def test_feedback_score_out_of_range_rejected(client):
    c, _ = client
    assert c.post("/feedback", json=_payload(score=0)).status_code == 422
    assert c.post("/feedback", json=_payload(score=3)).status_code == 422


def test_feedback_score_and_comment_optional(client):
    c, captured = client
    r = c.post("/feedback", json=_payload(score=None, comment=None))
    assert r.status_code == 201
    assert captured[-1].score is None
    assert captured[-1].comment is None


def test_feedback_missing_session_id_autofilled(client):
    c, captured = client
    body = _payload()
    del body["session_id"]
    r = c.post("/feedback", json=body)
    assert r.status_code == 201
    uuid.UUID(captured[-1].session_id)  # server-generated UUID


def test_feedback_missing_skill_name_rejected(client):
    c, _ = client
    body = _payload()
    del body["skill_name"]
    assert c.post("/feedback", json=body).status_code == 422


def test_feedback_missing_agent_rejected(client):
    c, _ = client
    body = _payload()
    del body["agent"]
    assert c.post("/feedback", json=body).status_code == 422


def test_feedback_created_at_autofilled(client):
    c, captured = client
    r = c.post("/feedback", json=_payload())
    assert r.status_code == 201
    assert captured[-1].created_at.endswith("Z")


def test_feedback_created_at_preserved(client):
    c, captured = client
    r = c.post("/feedback", json=_payload(created_at="2026-01-01T00:00:00Z"))
    assert r.status_code == 201
    assert captured[-1].created_at == "2026-01-01T00:00:00Z"


def test_feedback_store_failure_returns_503(failing_client):
    r = failing_client.post("/feedback", json=_payload())
    assert r.status_code == 503
    assert "store failed" in r.json()["detail"]


def test_feedback_request_id_propagated(client):
    c, captured = client
    r = c.post("/feedback", json=_payload(request_id="req-abc"))
    assert r.status_code == 201
    assert captured[-1].request_id == "req-abc"
