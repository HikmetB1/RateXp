"""The interface every redaction adapter implements.

Adapters live in this package (redact_with_azure.py, redact_with_presidio.py)
and are chosen at runtime by config.yaml's ``redaction.provider`` (see
../redact_trajectory.py). An adapter only turns a batch of texts into their
PII-masked versions; the ATIF walking, field selection and fail-closed handling
stay in ../redact_trajectory.py, so adapters stay small.

To add a provider: drop a ``redact_with_<name>.py`` here with a class implementing
``redact_texts`` and wire it into ``get_redactor`` (../redact_trajectory.py).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Redactor(Protocol):
    def redact_texts(self, texts: list[str]) -> list[str]:
        """Return each input text with personal data masked, same order and length.

        Must raise on any failure so the caller drops the upload (fail-closed).
        """
        ...
