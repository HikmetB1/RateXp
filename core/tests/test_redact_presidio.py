"""PresidioRedactor smoke test.

Skipped unless the redaction-presidio extra and its spaCy model are installed
(they aren't in the default test env), so CI stays green without the heavy deps.
"""

from __future__ import annotations

import pytest

pytest.importorskip("presidio_analyzer")
pytest.importorskip("presidio_anonymizer")
pytest.importorskip("langdetect")


def test_masks_email_and_name():
    from redaction_adapters.presidio import PresidioRedactor

    out = PresidioRedactor(languages=["en"]).redact_texts(
        ["Contact John Smith at john@example.com"]
    )[0]
    assert "john@example.com" not in out
    assert "John Smith" not in out
