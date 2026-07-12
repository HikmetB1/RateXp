"""dispatch fan-out: writes to every adapter, independent and non-fatal."""

from __future__ import annotations

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


def test_writes_to_every_adapter(monkeypatch):
    import dispatch

    a, b = _Recorder("a"), _Recorder("b")
    monkeypatch.setattr(dispatch, "_adapters", [a, b])
    dispatch.write_feedback(Feedback(skill_name="demo", agent="cc"))
    assert len(a.feedback) == 1 and len(b.feedback) == 1


def test_one_failure_does_not_stop_others_or_raise(monkeypatch):
    import dispatch

    bad, good = _Recorder("bad", boom=True), _Recorder("good")
    monkeypatch.setattr(dispatch, "_adapters", [bad, good])
    # Must not raise even though `bad` blows up; `good` still gets the record.
    dispatch.write_transcript(Transcript(skill_name="demo", agent="cc", atif={"steps": []}))
    assert len(good.transcripts) == 1


def test_close_adapters_closes_all_and_resets(monkeypatch):
    import dispatch

    a, b = _Recorder("a"), _Recorder("b")
    monkeypatch.setattr(dispatch, "_adapters", [a, b])
    dispatch.close_adapters()
    assert a.closed and b.closed
    assert dispatch._adapters is None
