"""Azure PII redaction of ATIF transcripts (redact.py).

Azure is never called for real: the SDK client is monkeypatched so these tests
exercise the collection, batching and fail-closed logic only.
"""

from __future__ import annotations

import pytest


class _FakeDoc:
    def __init__(self, id: str, redacted_text: str, *, is_error: bool = False, error=None):
        self.id = id
        self.redacted_text = redacted_text
        self.is_error = is_error
        self.error = error


class _FakeLang:
    """Stands in for a detect_language result; reports a fixed ISO code."""

    def __init__(self, iso: str = "en"):
        self.is_error = False
        self.error = None
        self.primary_language = type("PL", (), {"iso6391_name": iso, "confidence_score": 1.0})()


class _FakeClient:
    """Records each PII batch and masks every document to a fixed marker."""

    def __init__(self, detect_iso: str = "en"):
        self.batches: list[list[dict]] = []
        self._detect_iso = detect_iso

    def detect_language(self, documents):
        return [_FakeLang(self._detect_iso) for _ in documents]

    def recognize_pii_entities(self, documents, language=None):
        self.batches.append(list(documents))
        return [_FakeDoc(d["id"], "[REDACTED]") for d in documents]


def test_redact_disabled_is_noop(monkeypatch):
    import redact

    monkeypatch.setattr(redact, "REDACTION_ENABLED", False)
    atif = {"steps": [{"message": "I am Hikmet, a@b.com"}]}
    assert redact.redact_atif(atif)["steps"][0]["message"] == "I am Hikmet, a@b.com"


def test_redact_masks_conversation_fields(monkeypatch):
    import redact

    monkeypatch.setattr(redact, "REDACTION_ENABLED", True)
    fake = _FakeClient()
    monkeypatch.setattr(redact, "_make_client", lambda: fake)

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
    # 4 text fields → one batch of 4 documents.
    assert [len(b) for b in fake.batches] == [4]


def test_redact_enabled_no_text_skips_azure(monkeypatch):
    import redact

    monkeypatch.setattr(redact, "REDACTION_ENABLED", True)

    def boom():
        raise AssertionError("client must not be built when there is no text")

    monkeypatch.setattr(redact, "_make_client", boom)
    atif = {"steps": [{"source": "agent", "tool_calls": [{"name": "Bash"}]}]}
    assert redact.redact_atif(atif) == atif


def test_redact_batches_in_fives(monkeypatch):
    import redact

    monkeypatch.setattr(redact, "REDACTION_ENABLED", True)
    fake = _FakeClient()
    monkeypatch.setattr(redact, "_make_client", lambda: fake)

    atif = {"steps": [{"message": f"m{i}"} for i in range(7)]}
    redact.redact_atif(atif)
    assert [len(b) for b in fake.batches] == [5, 2]


def test_redact_uses_detected_language(monkeypatch):
    import redact

    monkeypatch.setattr(redact, "REDACTION_ENABLED", True)
    monkeypatch.setattr(redact, "REDACTION_LANGUAGES", ["en", "zh-hans", "es"])
    monkeypatch.setattr(redact, "REDACTION_LANGUAGE", "en")
    monkeypatch.setattr(redact, "_LANG_BY_ISO", {"en": "en", "zh": "zh-hans", "es": "es"})
    # Detection reports Chinese → the configured "zh-hans" code is passed to PII.
    fake = _FakeClient(detect_iso="zh")
    monkeypatch.setattr(redact, "_make_client", lambda: fake)

    redact.redact_atif({"steps": [{"message": "你好 a@b.com"}]})
    assert fake.batches[0][0]["language"] == "zh-hans"


def test_redact_unknown_language_falls_back_to_default(monkeypatch):
    import redact

    monkeypatch.setattr(redact, "REDACTION_ENABLED", True)
    monkeypatch.setattr(redact, "REDACTION_LANGUAGES", ["en", "es"])
    monkeypatch.setattr(redact, "REDACTION_LANGUAGE", "en")
    monkeypatch.setattr(redact, "_LANG_BY_ISO", {"en": "en", "es": "es"})
    # Detected language ("ja") is not configured → fall back to the first ("en").
    fake = _FakeClient(detect_iso="ja")
    monkeypatch.setattr(redact, "_make_client", lambda: fake)

    redact.redact_atif({"steps": [{"message": "こんにちは"}]})
    assert fake.batches[0][0]["language"] == "en"


def test_redact_retries_rejected_language_with_fallback(monkeypatch):
    import redact

    monkeypatch.setattr(redact, "REDACTION_ENABLED", True)
    monkeypatch.setattr(redact, "REDACTION_LANGUAGE", "en")

    class RetryClient:
        """Errors on the first (detected-language) call, succeeds on the retry."""

        def __init__(self):
            self.calls = 0

        def detect_language(self, documents):
            return [_FakeLang("zh") for _ in documents]

        def recognize_pii_entities(self, documents, language=None):
            self.calls += 1
            if self.calls == 1:
                return [
                    _FakeDoc(d["id"], "", is_error=True, error="unsupported") for d in documents
                ]
            return [_FakeDoc(d["id"], "[REDACTED]") for d in documents]

    client = RetryClient()
    monkeypatch.setattr(redact, "_make_client", lambda: client)
    out = redact.redact_atif({"steps": [{"message": "hi"}]})
    assert out["steps"][0]["message"] == "[REDACTED]"
    assert client.calls == 2  # first attempt + fallback retry


def test_redact_doc_error_is_fail_closed(monkeypatch):
    import redact

    monkeypatch.setattr(redact, "REDACTION_ENABLED", True)

    class ErrClient:
        def detect_language(self, documents):
            return [_FakeLang("en") for _ in documents]

        def recognize_pii_entities(self, documents, language=None):
            # Errors on every call, including the fallback retry → fail-closed.
            return [_FakeDoc(d["id"], "", is_error=True, error="bad input") for d in documents]

    monkeypatch.setattr(redact, "_make_client", lambda: ErrClient())
    with pytest.raises(RuntimeError):
        redact.redact_atif({"steps": [{"message": "hi"}]})


def test_make_client_requires_endpoint(monkeypatch):
    import redact

    monkeypatch.setattr(redact, "REDACTION_ENDPOINT", "")
    with pytest.raises(RuntimeError):
        redact._make_client()
