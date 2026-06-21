"""AzureRedactor: 5-doc batching, per-doc language detect/fallback, retry, fail-closed.

Azure is never called for real - the SDK client is replaced with a fake, so these
exercise the adapter's batching and language logic only.
"""

from __future__ import annotations

import pytest
from redaction_adapters.azure import AzureRedactor


class _FakeDoc:
    def __init__(self, id: str, redacted_text: str, *, is_error: bool = False, error=None):
        self.id = id
        self.redacted_text = redacted_text
        self.is_error = is_error
        self.error = error


class _FakeLang:
    def __init__(self, iso: str = "en"):
        self.is_error = False
        self.error = None
        self.primary_language = type("PL", (), {"iso6391_name": iso})()


class _FakeClient:
    """Records each PII batch and masks every document to a fixed marker."""

    def __init__(self, detect_iso: str = "en"):
        self.batches: list[list[dict]] = []
        self._detect_iso = detect_iso

    def detect_language(self, documents):
        return [_FakeLang(self._detect_iso) for _ in documents]

    def recognize_pii_entities(self, documents):
        self.batches.append(list(documents))
        return [_FakeDoc(d["id"], "[REDACTED]") for d in documents]


def _adapter(client, languages=("en", "zh-hans", "es")):
    a = AzureRedactor(endpoint="https://x/", languages=list(languages))
    a._client = client  # bypass the lazy SDK build
    return a


def test_requires_endpoint():
    with pytest.raises(RuntimeError):
        AzureRedactor(endpoint="", languages=["en"])


def test_batches_in_fives():
    fake = _FakeClient()
    out = _adapter(fake).redact_texts([f"m{i}" for i in range(7)])
    assert out == ["[REDACTED]"] * 7
    assert [len(b) for b in fake.batches] == [5, 2]


def test_uses_detected_language():
    fake = _FakeClient(detect_iso="zh")
    _adapter(fake).redact_texts(["你好 a@b.com"])
    assert fake.batches[0][0]["language"] == "zh-hans"


def test_unknown_language_falls_back():
    fake = _FakeClient(detect_iso="ja")  # not configured -> fall back to first ("en")
    _adapter(fake, languages=("en", "es")).redact_texts(["こんにちは"])
    assert fake.batches[0][0]["language"] == "en"


def test_retries_rejected_language_with_fallback():
    class RetryClient:
        def __init__(self):
            self.calls = 0

        def detect_language(self, documents):
            return [_FakeLang("zh") for _ in documents]

        def recognize_pii_entities(self, documents):
            self.calls += 1
            if self.calls == 1:
                return [
                    _FakeDoc(d["id"], "", is_error=True, error="unsupported") for d in documents
                ]
            return [_FakeDoc(d["id"], "[REDACTED]") for d in documents]

    c = RetryClient()
    assert _adapter(c).redact_texts(["hi"]) == ["[REDACTED]"]
    assert c.calls == 2  # first attempt + fallback retry


def test_doc_error_is_fail_closed():
    class ErrClient:
        def detect_language(self, documents):
            return [_FakeLang("en") for _ in documents]

        def recognize_pii_entities(self, documents):
            return [_FakeDoc(d["id"], "", is_error=True, error="bad input") for d in documents]

    with pytest.raises(RuntimeError):
        _adapter(ErrClient()).redact_texts(["hi"])
