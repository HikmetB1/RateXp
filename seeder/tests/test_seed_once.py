"""One run end to end, with the skill run and the two posts stubbed out."""

from __future__ import annotations

from api import seed_once as seed_module
from api.record_schemas import Rating
from api.seed_once import seed_once

_SKILL = {"name": "demo", "prompt": "x"}


def _stub_run(monkeypatch, result):
    monkeypatch.setattr(seed_module, "load_skill_pool", lambda: (_SKILL,))
    monkeypatch.setattr(seed_module, "run_skill_task", lambda skill: result)


def test_a_rated_run_submits_both_records(monkeypatch):
    _stub_run(monkeypatch, (Rating(score=1, comment="clear"), ["m"]))
    submitted = []
    monkeypatch.setattr(
        seed_module,
        "post_feedback",
        lambda run, rating: submitted.append(("feedback", run)) is None,
    )
    monkeypatch.setattr(
        seed_module,
        "post_transcript",
        lambda run, messages: submitted.append(("transcript", run)) is None,
    )

    assert seed_once() == {"skill": "demo", "feedback_sent": True, "transcript_stored": True}
    # Both posts describe the same run.
    assert [kind for kind, _ in submitted] == ["feedback", "transcript"]
    assert submitted[0][1].request_id == submitted[1][1].request_id


def test_an_unrated_run_still_submits_its_transcript(monkeypatch):
    _stub_run(monkeypatch, (None, ["m"]))
    monkeypatch.setattr(seed_module, "post_feedback", lambda run, rating: True)
    monkeypatch.setattr(seed_module, "post_transcript", lambda run, messages: True)

    assert seed_once() == {"skill": "demo", "feedback_sent": False, "transcript_stored": True}


def test_a_failed_run_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(seed_module, "load_skill_pool", lambda: (_SKILL,))

    def boom(skill):
        raise RuntimeError("nope")

    monkeypatch.setattr(seed_module, "run_skill_task", boom)
    assert seed_once() == {
        "skill": "demo",
        "feedback_sent": False,
        "transcript_stored": False,
        "error": "nope",
    }


def test_an_empty_skill_pool_is_reported(monkeypatch):
    monkeypatch.setattr(seed_module, "load_skill_pool", lambda: ())
    result = seed_once()
    assert result["skill"] is None
    assert "no skills" in result["error"]
