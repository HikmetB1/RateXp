"""Pick a redaction adapter by name. A provider's optional deps import lazily, so
core runs without them unless that provider is actually selected.
"""

from __future__ import annotations

from .base import Redactor


def get_redactor(provider: str, *, endpoint: str, languages: list[str]) -> Redactor:
    """Build the adapter named by config.yaml's ``redaction.provider``."""
    if provider == "presidio":
        from .presidio import PresidioRedactor

        return PresidioRedactor(languages=languages)
    if provider == "azure":
        from .azure import AzureRedactor

        return AzureRedactor(endpoint=endpoint, languages=languages)
    raise RuntimeError(f"unknown redaction.provider {provider!r}; use 'presidio' or 'azure'")


__all__ = ["Redactor", "get_redactor"]
