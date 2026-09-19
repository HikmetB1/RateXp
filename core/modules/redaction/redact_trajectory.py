"""PII redaction for consented transcripts, via a pluggable adapter.

``redact_atif`` walks the ATIF conversation text, hands it to the adapter named
by config.yaml ``redaction.provider`` (see adapters/), and writes the masked text
back. Fail-closed: any adapter error propagates so the caller drops the upload.
The adapter (and its optional deps) is built lazily on first use, so core runs
without those deps when redaction is off.
"""

from __future__ import annotations

from load_config import (
    REDACTION_ENABLED,
    REDACTION_ENDPOINT,
    REDACTION_LANGUAGES,
    REDACTION_PROVIDER,
)
from modules.redaction.adapters.redactor_interface import Redactor

# ATIF step fields holding free-form conversation text we redact.
_TEXT_FIELDS = ("message", "reasoning_content", "observation")

# The chosen adapter, built once on first use (loads its deps / model). None until then.
_redactor = None


def is_enabled() -> bool:
    return bool(REDACTION_ENABLED)


def get_redactor(provider: str, *, endpoint: str, languages: list[str]) -> Redactor:
    """Build the adapter named by config.yaml's ``redaction.provider``.

    A provider's optional deps import here rather than at module scope, so core
    runs without them unless that provider is the one actually selected.
    """
    if provider == "presidio":
        from modules.redaction.adapters.redact_with_presidio import PresidioRedactor

        return PresidioRedactor(languages=languages)
    if provider == "azure":
        from modules.redaction.adapters.redact_with_azure import AzureRedactor

        return AzureRedactor(endpoint=endpoint, languages=languages)
    raise RuntimeError(f"unknown redaction.provider {provider!r}; use 'presidio' or 'azure'")


def _configured_redactor() -> Redactor:
    global _redactor
    if _redactor is None:
        _redactor = get_redactor(
            REDACTION_PROVIDER, endpoint=REDACTION_ENDPOINT, languages=REDACTION_LANGUAGES
        )
    return _redactor


def redact_atif(atif: dict) -> dict:
    """Return the ATIF trajectory with conversation text PII-masked.

    No-op (returns the input unchanged) when redaction is disabled. When enabled,
    any adapter error propagates so the caller can drop the upload (fail-closed).
    The input dict is mutated in place and also returned.
    """
    if not is_enabled():
        return atif
    steps = atif.get("steps")
    if not isinstance(steps, list):
        return atif

    # Collect every non-empty text field as (step_index, field) -> value, so we hand
    # the whole conversation to the adapter at once and write the masked text back.
    targets: list[tuple[int, str]] = []
    texts: list[str] = []
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        for field in _TEXT_FIELDS:
            val = step.get(field)
            if isinstance(val, str) and val.strip():
                targets.append((i, field))
                texts.append(val)
    if not texts:
        return atif

    redacted = _configured_redactor().redact_texts(texts)
    for (i, field), value in zip(targets, redacted, strict=True):
        steps[i][field] = value
    return atif
