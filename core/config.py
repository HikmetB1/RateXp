"""Loads runtime config from config.yaml.

Resolved relative to this file so the working directory doesn't matter. Every
key is required - no in-code fallbacks, so a missing key fails loudly at startup.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

_CONFIG_FILE = Path(__file__).resolve().parent / "config.yaml"
_config: dict = yaml.safe_load(_CONFIG_FILE.read_text(encoding="utf-8")) or {}


def _require(key: str):
    if key not in _config:
        raise RuntimeError(f"config.yaml is missing required key: {key!r}")
    return _config[key]


def _require_in(parent: dict, parent_name: str, key: str):
    if not isinstance(parent, dict) or key not in parent:
        raise RuntimeError(f"config.yaml is missing required key: {parent_name}.{key!r}")
    return parent[key]


SCHEMA_VERSION: str = _require("schema_version")
MAX_BODY_BYTES: int = _require("max_body_bytes")
MAX_TRANSCRIPT_BYTES: int = _require("max_transcript_bytes")
RATE_LIMIT_PER_MINUTE: int = _require("rate_limit_per_minute")
DEFAULT_SURVEY_EVERY: int = _require("default_survey_every")
if DEFAULT_SURVEY_EVERY < 1:
    raise RuntimeError(f"default_survey_every must be >= 1, got {DEFAULT_SURVEY_EVERY}")

# PII redaction config (see redact.py).
_REDACTION: dict = _require("redaction")
# RATEXP_REDACTION_ENABLED overrides config.yaml, so a local stack (no Azure
# identity) can disable redaction without editing the cloud-bound file. Truthy: 1/true/yes/on.
_REDACTION_ENABLED_DEFAULT: bool = bool(_require_in(_REDACTION, "redaction", "enabled"))
_REDACTION_ENABLED_ENV = os.getenv("RATEXP_REDACTION_ENABLED")
REDACTION_ENABLED: bool = (
    _REDACTION_ENABLED_ENV.strip().lower() in ("1", "true", "yes", "on")
    if _REDACTION_ENABLED_ENV is not None
    else _REDACTION_ENABLED_DEFAULT
)
REDACTION_ENDPOINT: str = str(_require_in(_REDACTION, "redaction", "endpoint") or "")
_REDACTION_LANGUAGES = _require_in(_REDACTION, "redaction", "languages")
if not isinstance(_REDACTION_LANGUAGES, list) or not _REDACTION_LANGUAGES:
    raise RuntimeError("config.yaml redaction.languages must be a non-empty list")
# Accepted PII languages; the first is the fallback when detection misses.
REDACTION_LANGUAGES: list[str] = [str(x) for x in _REDACTION_LANGUAGES]
REDACTION_LANGUAGE: str = REDACTION_LANGUAGES[0]
