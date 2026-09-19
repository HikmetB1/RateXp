"""The Azure AI Language adapter: batching, language choice, retry, fail-closed.

Azure is never called. The SDK client is replaced with a fake, so these cover the
adapter's own logic and nothing else. Billing is per 1,000 text records, which is
why the batch sizes below are worth asserting on.
"""

from __future__ import annotations

import pytest
from modules.redaction.adapters.redact_with_azure import AzureRedactor


class _FakeDoc:
    def __init__(self, id: str, redacted_text: str, *, is_error: bool = False, error=None):
        self.id = id
        self.redacted_text = redacted_text
        self.is_error = is_error
        self.error = error


class _FakeLanguage:
    def __init__(self, iso: str):
        self.is_error = False
        self.error = None
        self.primary_language = type("PrimaryLanguage", (), {"iso6391_name": iso})()


class _FakeClient:
    """Records each PII batch and masks every document to a fixed marker."""

    def __init__(self, detected_iso: str = "en"):
        self.batches: list[list[dict]] = []
        self._detected_iso = detected_iso

    def detect_language(self, documents):
        return [_FakeLanguage(self._detected_iso) for _ in documents]

    def recognize_pii_entities(self, documents):
        self.batches.append(list(documents))
        return [_FakeDoc(d["id"], "[REDACTED]") for d in documents]


def _adapter(client, languages=("en", "zh-hans", "es")) -> AzureRedactor:
    adapter = AzureRedactor(endpoint="https://x/", languages=list(languages))
    adapter._client = client  # skip the lazy SDK build
    return adapter


def test_an_empty_endpoint_is_refused_at_construction():
    # Better a loud failure at startup than a silent one on the first upload.
    with pytest.raises(RuntimeError):
        AzureRedactor(endpoint="", languages=["en"])


def test_texts_are_sent_five_at_a_time():
    # Azure AI Language accepts at most 5 documents per PII request.
    fake = _FakeClient()
    masked = _adapter(fake).redact_texts([f"m{i}" for i in range(7)])
    assert masked == ["[REDACTED]"] * 7
    assert [len(batch) for batch in fake.batches] == [5, 2]


def test_the_detected_language_is_mapped_to_the_configured_code():
    # Detection returns ISO 639-1 ("zh"); the PII model wants the configured
    # BCP-47 code ("zh-hans").
    fake = _FakeClient(detected_iso="zh")
    _adapter(fake).redact_texts(["你好 a@b.com"])
    assert fake.batches[0][0]["language"] == "zh-hans"


def test_a_language_nobody_configured_falls_back_to_the_first_one():
    fake = _FakeClient(detected_iso="ja")
    _adapter(fake, languages=("en", "es")).redact_texts(["こんにちは"])
    assert fake.batches[0][0]["language"] == "en"


def test_a_document_the_model_rejects_is_retried_in_the_fallback_language():
    class RejectsOnceClient:
        def __init__(self):
            self.calls = 0

        def detect_language(self, documents):
            return [_FakeLanguage("zh") for _ in documents]

        def recognize_pii_entities(self, documents):
            self.calls += 1
            if self.calls == 1:
                return [
                    _FakeDoc(d["id"], "", is_error=True, error="unsupported") for d in documents
                ]
            return [_FakeDoc(d["id"], "[REDACTED]") for d in documents]

    client = RejectsOnceClient()
    assert _adapter(client).redact_texts(["hi"]) == ["[REDACTED]"]
    assert client.calls == 2  # the first attempt, then the fallback retry


def test_a_document_that_fails_the_retry_too_is_fail_closed():
    class AlwaysErrorsClient:
        def detect_language(self, documents):
            return [_FakeLanguage("en") for _ in documents]

        def recognize_pii_entities(self, documents):
            return [_FakeDoc(d["id"], "", is_error=True, error="bad input") for d in documents]

    # Returning "" for an unmaskable document would silently drop the text and
    # look like a successful redaction, so it has to raise.
    with pytest.raises(RuntimeError):
        _adapter(AlwaysErrorsClient()).redact_texts(["hi"])
