"""Both kinds of run end to end, with the agent run and the two posts stubbed out."""

from __future__ import annotations

import pytest
from api import seed_once as seed_module
from api.record_schemas import Rating
from api.seed_once import seed_session_once, seed_skill_once

_SKILL = {"name": "demo", "prompt": "x"}


@pytest.fixture(autouse=True)
def one_focus(monkeypatch):
    monkeypatch.setattr(seed_module, "COMMENT_FOCUSES", ["the speed"])


@pytest.fixture
def submitted(monkeypatch):
    """Every post the run makes, as ``(kind, run, rating)``; both report success."""
    sent = []
    monkeypatch.setattr(
        seed_module,
        "post_feedback",
        lambda run, rating: sent.append(("feedback", run, rating)) is None,
    )
    monkeypatch.setattr(
        seed_module,
        "post_transcript",
        lambda run, messages, rating: sent.append(("transcript", run, rating)) is None,
    )
    return sent


def _stub_skill_run(monkeypatch, result):
    monkeypatch.setattr(seed_module, "load_skill_pool", lambda: (_SKILL,))
    monkeypatch.setattr(seed_module, "run_skill_task", lambda skill, focus: result)


def test_a_rated_skill_run_submits_both_records(monkeypatch, submitted):
    rating = Rating(score=1, comment="clear")
    _stub_skill_run(monkeypatch, (rating, ["m"]))

    assert seed_skill_once() == {
        "skill": "demo",
        "focus": "the speed",
        "feedback_sent": True,
        "transcript_stored": True,
    }
    # Both posts describe the same run, and both carry its rating.
    assert [kind for kind, _, _ in submitted] == ["feedback", "transcript"]
    assert submitted[0][1].request_id == submitted[1][1].request_id
    assert submitted[0][1].skill_name == "demo"
    assert [sent_rating for _, _, sent_rating in submitted] == [rating, rating]


def test_a_session_run_submits_both_records_with_no_skill(monkeypatch, submitted):
    monkeypatch.setattr(seed_module, "SESSION_TASKS", ["write a todo app"])
    monkeypatch.setattr(
        seed_module,
        "run_session_task",
        lambda task, focus: (Rating(score=1, comment="done"), ["m"]),
    )

    assert seed_session_once() == {
        "session": "write a todo app",
        "focus": "the speed",
        "feedback_sent": True,
        "transcript_stored": True,
    }
    assert [run.skill_name for _, run, _ in submitted] == [None, None]


def test_each_run_hands_the_agent_its_focus(monkeypatch, submitted):
    focuses = []
    monkeypatch.setattr(seed_module, "load_skill_pool", lambda: (_SKILL,))
    monkeypatch.setattr(seed_module, "SESSION_TASKS", ["write a todo app"])
    for name in ("run_skill_task", "run_session_task"):
        monkeypatch.setattr(seed_module, name, lambda _, focus: focuses.append(focus) or (None, []))

    seed_skill_once()
    seed_session_once()
    assert focuses == ["the speed", "the speed"]


def test_an_unrated_run_still_submits_its_transcript(monkeypatch, submitted):
    _stub_skill_run(monkeypatch, (None, ["m"]))

    assert seed_skill_once() == {
        "skill": "demo",
        "focus": "the speed",
        "feedback_sent": False,
        "transcript_stored": True,
    }
    assert [(kind, rating) for kind, _, rating in submitted] == [("transcript", None)]


def test_a_failed_run_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(seed_module, "load_skill_pool", lambda: (_SKILL,))

    def boom(skill, focus):
        raise RuntimeError("nope")

    monkeypatch.setattr(seed_module, "run_skill_task", boom)
    assert seed_skill_once() == {
        "skill": "demo",
        "focus": "the speed",
        "feedback_sent": False,
        "transcript_stored": False,
        "error": "nope",
    }


def test_an_empty_skill_pool_is_reported(monkeypatch):
    monkeypatch.setattr(seed_module, "load_skill_pool", lambda: ())
    result = seed_skill_once()
    assert result["skill"] is None
    assert "no skills" in result["error"]
