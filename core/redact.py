"""Azure AI Language PII redaction for consented transcripts.

When enabled (config.yaml ``redaction.enabled``), each transcript's conversation
text is sent to Azure for PII detection and only the masked text is stored; the
raw text never reaches the database. Fail-closed: any Azure error makes
:func:`redact_atif` raise so the caller drops the upload.

No secret is stored - like the database, core authenticates with its Managed
Identity (Entra ID). The Azure SDK is an optional extra imported lazily, so core
runs without it when redaction is off.

Multi-language: each message's language is auto-detected and used for PII if it's
one of the configured ``languages``, else the first is the fallback. A document
the PII model rejects is retried once with the fallback.
"""

from __future__ import annotations

from config import (
    REDACTION_ENABLED,
    REDACTION_ENDPOINT,
    REDACTION_LANGUAGE,
    REDACTION_LANGUAGES,
)

# ATIF step fields holding free-form conversation text we redact.
_TEXT_FIELDS = ("message", "reasoning_content", "observation")
# Azure AI Language accepts at most 5 documents per PII request.
_BATCH = 5
# Detected ISO 639-1 code (e.g. "zh") -> the configured PII code (e.g. "zh-hans").
_LANG_BY_ISO = {code.split("-", 1)[0].lower(): code for code in REDACTION_LANGUAGES}


def is_enabled() -> bool:
    return bool(REDACTION_ENABLED)


def _make_client():
    """Build an Azure Text Analytics client authenticated with the Managed Identity."""
    if not REDACTION_ENDPOINT:
        raise RuntimeError("redaction enabled but redaction.endpoint is empty in config.yaml")
    from azure.ai.textanalytics import TextAnalyticsClient
    from azure.identity import DefaultAzureCredential

    return TextAnalyticsClient(REDACTION_ENDPOINT, DefaultAzureCredential())


def _detect_languages(client, texts: list[str]) -> list[str]:
    """Pick a PII language per document: the auto-detected one if it's configured,
    else the fallback (first configured language)."""
    langs: list[str] = []
    for doc in client.detect_language(texts):
        iso = "" if doc.is_error else (doc.primary_language.iso6391_name or "").lower()
        langs.append(_LANG_BY_ISO.get(iso, REDACTION_LANGUAGE))
    return langs


def _redact_batch(client, texts: list[str]) -> list[str]:
    """Redact up to _BATCH documents, each in its auto-detected language."""
    langs = _detect_languages(client, texts)
    docs = [{"id": str(i), "text": t, "language": langs[i]} for i, t in enumerate(texts)]
    out: list[str] = [""] * len(texts)
    retry: list[int] = []
    for doc in client.recognize_pii_entities(docs):
        i = int(doc.id)
        if doc.is_error:
            retry.append(i)  # detected language may be unsupported - try the fallback
        else:
            out[i] = doc.redacted_text
    if retry:
        rdocs = [{"id": str(i), "text": texts[i], "language": REDACTION_LANGUAGE} for i in retry]
        for doc in client.recognize_pii_entities(rdocs):
            if doc.is_error:
                raise RuntimeError(f"Azure PII redaction failed: {doc.error}")
            out[int(doc.id)] = doc.redacted_text
    return out


def redact_atif(atif: dict) -> dict:
    """Return the ATIF trajectory with conversation text PII-masked.

    No-op (returns the input unchanged) when redaction is disabled. When enabled,
    any Azure error propagates so the caller can drop the upload (fail-closed).
    The input dict is mutated in place and also returned.
    """
    if not is_enabled():
        return atif
    steps = atif.get("steps")
    if not isinstance(steps, list):
        return atif

    # Collect every non-empty text field as (step_index, field) -> value, so we
    # can batch them all to Azure and write the redacted text straight back.
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

    client = _make_client()
    redacted: list[str] = []
    for start in range(0, len(texts), _BATCH):
        redacted.extend(_redact_batch(client, texts[start : start + _BATCH]))

    for (i, field), value in zip(targets, redacted, strict=True):
        steps[i][field] = value
    return atif
