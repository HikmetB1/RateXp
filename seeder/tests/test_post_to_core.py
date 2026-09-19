"""Submitting to core: the two bodies that go on the wire, and never raising."""

from __future__ import annotations

import urllib.error

from api.record_schemas import Rating
from modules.submit import build_trajectory, post_to_core
from modules.submit.post_to_core import post_feedback, post_transcript


def test_feedback_goes_out_as_json(run, posted, monkeypatch):
    monkeypatch.setattr(post_to_core, "CORE_URL", "http://core")

    assert post_feedback(run, Rating(score=2, comment="clunky")) is True
    sent = posted.sent[0]
    assert sent["url"] == "http://core/feedback"
    assert sent["method"] == "POST"
    assert sent["headers"]["content-type"] == "application/json"
    assert sent["body"] == {
        "skill_name": "demo",
        "agent": "langchain gpt-4o-mini",
        "session_id": "s",
        "request_id": "r",
        "score": 2,
        "comment": "clunky",
    }


def test_transcript_carries_the_atif_under_the_same_ids(run, posted, monkeypatch):
    monkeypatch.setattr(post_to_core, "CORE_URL", "http://core")
    monkeypatch.setattr(build_trajectory, "OVERSIZED_RATIO", 0)

    assert post_transcript(run, []) is True
    sent = posted.sent[0]
    assert sent["url"] == "http://core/transcript"
    assert sent["body"]["request_id"] == "r"
    assert sent["body"]["atif"]["session_id"] == "s"


def test_a_non_2xx_answer_is_not_accepted(run, posted):
    posted.status = 500
    assert post_feedback(run, Rating(score=1, comment="fine")) is False


def test_core_being_down_is_reported_not_raised(run, monkeypatch):
    def boom(request, timeout=None):
        raise urllib.error.URLError("core is down")

    monkeypatch.setattr(post_to_core.urllib.request, "urlopen", boom)
    assert post_feedback(run, Rating(score=1, comment="fine")) is False
