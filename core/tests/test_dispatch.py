"""dispatch fan-out: writes to every adapter, at-least-one must accept."""

from __future__ import annotations

import logging

import pytest
from models import Feedback, Transcript


class _Recorder:
    def __init__(self, name, boom=False):
        self.name = name
        self.boom = boom
        self.feedback: list = []
        self.transcripts: list = []
        self.closed = False

    def write_feedback(self, record):
        if self.boom:
            raise RuntimeError(f"{self.name} down")
        self.feedback.append(record)

    def write_transcript(self, record):
        if self.boom:
            raise RuntimeError(f"{self.name} down")
        self.transcripts.append(record)

    def close(self):
        self.closed = True


def _feedback() -> Feedback:
    return Feedback(skill_name="demo", agent="cc")


def _transcript() -> Transcript:
    return Transcript(skill_name="demo", agent="cc", atif={"steps": []})


def test_writes_to_every_adapter(monkeypatch):
    import dispatch

    a, b = _Recorder("a"), _Recorder("b")
    monkeypatch.setattr(dispatch, "_adapters", [a, b])
    dispatch.write_feedback(_feedback())
    assert len(a.feedback) == 1 and len(b.feedback) == 1


def test_one_failure_does_not_stop_others_or_raise(monkeypatch):
    import dispatch

    bad, good = _Recorder("bad", boom=True), _Recorder("good")
    monkeypatch.setattr(dispatch, "_adapters", [bad, good])
    # `good` accepted the record, so the write succeeded despite `bad` blowing up.
    dispatch.write_transcript(_transcript())
    assert len(good.transcripts) == 1


def test_adapter_failure_is_logged(monkeypatch, caplog):
    import dispatch

    bad, good = _Recorder("bad", boom=True), _Recorder("good")
    monkeypatch.setattr(dispatch, "_adapters", [bad, good])
    with caplog.at_level(logging.WARNING):
        dispatch.write_feedback(_feedback())
    assert "bad" in caplog.text


def test_all_adapters_failing_raises_on_feedback(monkeypatch):
    import dispatch

    monkeypatch.setattr(
        dispatch, "_adapters", [_Recorder("a", boom=True), _Recorder("b", boom=True)]
    )
    # Nothing accepted the record, so the caller is told (server.py -> HTTP 503).
    with pytest.raises(dispatch.WriteError):
        dispatch.write_feedback(_feedback())


def test_all_adapters_failing_raises_on_transcript(monkeypatch):
    import dispatch

    monkeypatch.setattr(dispatch, "_adapters", [_Recorder("a", boom=True)])
    with pytest.raises(dispatch.WriteError):
        dispatch.write_transcript(_transcript())


def test_close_adapters_closes_all_and_resets(monkeypatch):
    import dispatch

    a, b = _Recorder("a"), _Recorder("b")
    monkeypatch.setattr(dispatch, "_adapters", [a, b])
    dispatch.close_adapters()
    assert a.closed and b.closed
    assert dispatch._adapters is None
