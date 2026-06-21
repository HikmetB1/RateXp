"""redact_atif dispatcher: field collection + fail-closed, with a fake adapter.

Adapter-specific behaviour (Azure batching, Presidio) is covered in
test_redact_azure.py / test_redact_presidio.py.
"""

from __future__ import annotations

import pytest


class _FakeRedactor:
    """Records each call's texts and masks every one to a fixed marker."""

    def __init__(self, mask: str = "[REDACTED]", boom: bool = False):
        self.calls: list[list[str]] = []
        self._mask = mask
        self._boom = boom

    def redact_texts(self, texts: list[str]) -> list[str]:
        self.calls.append(list(texts))
        if self._boom:
            raise RuntimeError("adapter failed")
        return [self._mask] * len(texts)


def _use(monkeypatch, redactor):
    """Enable redaction and pin the dispatcher to a fake adapter."""
    import redact

    monkeypatch.setattr(redact, "REDACTION_ENABLED", True)
    monkeypatch.setattr(redact, "_redactor", redactor)


def test_disabled_is_noop(monkeypatch):
    import redact

    monkeypatch.setattr(redact, "REDACTION_ENABLED", False)
    atif = {"steps": [{"message": "I am Hikmet, a@b.com"}]}
    assert redact.redact_atif(atif)["steps"][0]["message"] == "I am Hikmet, a@b.com"


def test_masks_conversation_fields(monkeypatch):
    import redact

    fake = _FakeRedactor()
    _use(monkeypatch, fake)
    atif = {
        "steps": [
            {"step_id": 1, "source": "user", "message": "I am Hikmet, a@b.com"},
            {"step_id": 2, "source": "agent", "message": "ok", "reasoning_content": "think"},
            {"step_id": 3, "source": "system", "observation": "result for 555-1234"},
        ]
    }
    out = redact.redact_atif(atif)
    assert out["steps"][0]["message"] == "[REDACTED]"
    assert out["steps"][1]["reasoning_content"] == "[REDACTED]"
    assert out["steps"][2]["observation"] == "[REDACTED]"
    # All four text fields handed to the adapter in one call, in order.
    assert fake.calls == [["I am Hikmet, a@b.com", "ok", "think", "result for 555-1234"]]


def test_no_text_skips_adapter(monkeypatch):
    import redact

    fake = _FakeRedactor()
    _use(monkeypatch, fake)
    atif = {"steps": [{"source": "agent", "tool_calls": [{"name": "Bash"}]}]}
    assert redact.redact_atif(atif) == atif
    assert fake.calls == []  # adapter never invoked when there is no text


def test_adapter_error_is_fail_closed(monkeypatch):
    import redact

    _use(monkeypatch, _FakeRedactor(boom=True))
    with pytest.raises(RuntimeError):
        redact.redact_atif({"steps": [{"message": "hi"}]})
