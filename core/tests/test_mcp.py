"""The `feedback` MCP tool - sampling and id injection (the old /snippet)."""

from __future__ import annotations

import re
import uuid

import mcp_app

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def test_feedback_every_one_always_surveys():
    # every=1 wins every roll, so the full survey prompt is always returned.
    # Match the question text, which is unique to the survey (skip.md also mentions
    # "AskUserQuestion", so that word can't tell survey from skip).
    for _ in range(20):
        assert "check all that apply" in mcp_app.feedback(every=1)


def test_feedback_injects_session_and_request_ids():
    body = mcp_app.feedback(every=1)
    assert "{{" not in body  # both placeholders substituted
    found = set(_UUID_RE.findall(body))
    for value in found:
        uuid.UUID(value)  # raises if not a valid UUID
    assert len(found) >= 2  # distinct session_id + request_id


def test_feedback_default_every_from_config(monkeypatch):
    # With no `every` the tool samples using config's default_survey_every.
    seen = []
    monkeypatch.setattr(mcp_app.random, "randrange", lambda n: seen.append(n) or 0)
    mcp_app.feedback()
    assert seen == [mcp_app.DEFAULT_SURVEY_EVERY]


def test_feedback_miss_returns_skip(monkeypatch):
    # On a "miss" the tool returns the short skip message instead of the survey.
    monkeypatch.setattr(mcp_app.random, "randrange", lambda _n: 1)
    body = mcp_app.feedback(every=5)
    assert "no survey this time" in body.lower()
    assert "check all that apply" not in body  # the survey prompt's question


def test_feedback_win_returns_survey(monkeypatch):
    # On a "win" (roll == 0) the normal survey prompt is returned, not the skip note.
    monkeypatch.setattr(mcp_app.random, "randrange", lambda _n: 0)
    body = mcp_app.feedback(every=5)
    assert "check all that apply" in body  # survey-only marker
    assert "no survey this time" not in body.lower()


def test_feedback_every_below_one_treated_as_one():
    # A bogus every (0) is clamped to 1, so it always surveys (no crash).
    assert "check all that apply" in mcp_app.feedback(every=0)
