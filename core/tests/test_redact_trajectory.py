"""Walking the trajectory and handing its text to whichever adapter is configured.

What the adapters themselves do is in test_redact_with_azure.py and
test_redact_with_presidio.py. conftest.py disables redaction for every test, so
each test here turns it back on explicitly.
"""

from __future__ import annotations

import pytest
from modules.redaction import redact_trajectory


class _FakeRedactor:
    """Records the texts of each call and masks every one to a fixed marker."""

    def __init__(self, *, boom: bool = False):
        self.calls: list[list[str]] = []
        self._boom = boom

    def redact_texts(self, texts: list[str]) -> list[str]:
        self.calls.append(list(texts))
        if self._boom:
            raise RuntimeError("provider failed")
        return ["[REDACTED]"] * len(texts)


def _enable(monkeypatch, redactor: _FakeRedactor) -> None:
    monkeypatch.setattr(redact_trajectory, "REDACTION_ENABLED", True)
    monkeypatch.setattr(redact_trajectory, "_redactor", redactor)


def test_disabled_redaction_leaves_the_trajectory_alone(monkeypatch):
    monkeypatch.setattr(redact_trajectory, "REDACTION_ENABLED", False)
    trajectory = {"steps": [{"message": "I am Hikmet, a@b.com"}]}
    masked = redact_trajectory.redact_atif(trajectory)
    assert masked["steps"][0]["message"] == "I am Hikmet, a@b.com"


def test_every_conversation_field_is_masked_in_one_call(monkeypatch):
    fake = _FakeRedactor()
    _enable(monkeypatch, fake)
    trajectory = {
        "steps": [
            {"step_id": 1, "source": "user", "message": "I am Hikmet, a@b.com"},
            {"step_id": 2, "source": "agent", "message": "ok", "reasoning_content": "think"},
            {"step_id": 3, "source": "system", "observation": "result for 555-1234"},
        ]
    }
    masked = redact_trajectory.redact_atif(trajectory)
    assert masked["steps"][0]["message"] == "[REDACTED]"
    assert masked["steps"][1]["reasoning_content"] == "[REDACTED]"
    assert masked["steps"][2]["observation"] == "[REDACTED]"
    # One call, not four. Azure bills per text record and Presidio pays a model
    # load, so batching the whole conversation is the point.
    assert fake.calls == [["I am Hikmet, a@b.com", "ok", "think", "result for 555-1234"]]


def test_fields_that_are_not_conversation_text_are_left_untouched(monkeypatch):
    # tool_calls carry arguments, not prose, and masking them would break replay.
    fake = _FakeRedactor()
    _enable(monkeypatch, fake)
    trajectory = {
        "steps": [{"source": "agent", "tool_calls": [{"name": "Bash", "arguments": {"cmd": "ls"}}]}]
    }
    assert redact_trajectory.redact_atif(trajectory) == trajectory


def test_a_trajectory_with_no_text_never_reaches_the_provider(monkeypatch):
    fake = _FakeRedactor()
    _enable(monkeypatch, fake)
    redact_trajectory.redact_atif({"steps": [{"source": "agent", "tool_calls": []}]})
    assert fake.calls == []


def test_a_provider_failure_propagates_so_the_upload_is_dropped(monkeypatch):
    # Fail-closed. Returning the text unmasked would be the worst possible
    # outcome, so the error has to reach the caller.
    _enable(monkeypatch, _FakeRedactor(boom=True))
    with pytest.raises(RuntimeError):
        redact_trajectory.redact_atif({"steps": [{"message": "hi"}]})


def test_an_unknown_provider_name_is_refused():
    with pytest.raises(RuntimeError):
        redact_trajectory.get_redactor("nosuchprovider", endpoint="", languages=["en"])


def test_a_comment_is_masked_as_one_text(monkeypatch):
    fake = _FakeRedactor()
    _enable(monkeypatch, fake)
    assert redact_trajectory.redact_text("Ann at a@b.com was slow") == "[REDACTED]"
    assert fake.calls == [["Ann at a@b.com was slow"]]


def test_a_comment_stays_as_typed_with_redaction_off(monkeypatch):
    monkeypatch.setattr(redact_trajectory, "REDACTION_ENABLED", False)
    assert redact_trajectory.redact_text("Ann at a@b.com") == "Ann at a@b.com"


def test_the_warm_up_builds_the_adapter_and_masks_once(monkeypatch):
    fake = _FakeRedactor()
    monkeypatch.setattr(redact_trajectory, "REDACTION_ENABLED", True)
    monkeypatch.setattr(redact_trajectory, "_redactor", None)
    monkeypatch.setattr(redact_trajectory, "get_redactor", lambda *_args, **_kwargs: fake)
    redact_trajectory.warm_up_redaction()
    assert redact_trajectory._redactor is fake
    assert len(fake.calls) == 1


def test_the_warm_up_does_nothing_with_redaction_off(monkeypatch):
    def never_built(*_args, **_kwargs):
        raise AssertionError("built an adapter while redaction is off")

    monkeypatch.setattr(redact_trajectory, "REDACTION_ENABLED", False)
    monkeypatch.setattr(redact_trajectory, "get_redactor", never_built)
    redact_trajectory.warm_up_redaction()
