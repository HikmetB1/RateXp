"""The Presidio adapter, against the real library.

Skipped unless the redaction-presidio extra and its spaCy model are installed.
They are not in the default test environment, because they are heavy and this is
the one suite that cannot fake its dependency: faking Presidio would only prove
the fake masks things.
"""

from __future__ import annotations

import pytest

pytest.importorskip("presidio_analyzer")
pytest.importorskip("presidio_anonymizer")
pytest.importorskip("langdetect")


def test_a_name_and_an_email_are_both_masked():
    from modules.redaction.adapters.redact_with_presidio import PresidioRedactor

    masked = PresidioRedactor(languages=["en"]).redact_texts(
        ["Contact John Smith at john@example.com"]
    )[0]
    assert "john@example.com" not in masked
    assert "John Smith" not in masked


def test_structured_pii_is_masked_even_in_a_language_spacy_cannot_model():
    """Arabic, Hindi, Bengali and Urdu are configured but have no spaCy NER model.

    Names in those languages get through, which is a known limit. Emails and the
    like must not, because those recognisers are patterns, not models.
    """
    from modules.redaction.adapters.redact_with_presidio import PresidioRedactor

    masked = PresidioRedactor(languages=["en", "ar"]).redact_texts(
        ["راسلني على john@example.com"]
    )[0]
    assert "john@example.com" not in masked
