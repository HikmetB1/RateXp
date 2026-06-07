"""Loads runtime config from config.yaml.

A single place for tunables that should live outside code, resolved relative to
this file so the working directory doesn't matter (tests, uvicorn, Docker all
find it). Every key is required — there are no in-code fallbacks, so the yaml is
the single source of truth and a missing key fails loudly at startup.
"""

from __future__ import annotations

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
RATE_LIMIT_PER_MINUTE: int = _require("rate_limit_per_minute")
DEFAULT_SURVEY_EVERY: int = _require("default_survey_every")
if DEFAULT_SURVEY_EVERY < 1:
    raise RuntimeError(f"default_survey_every must be >= 1, got {DEFAULT_SURVEY_EVERY}")

# Azure AI Language PII redaction for stored transcripts (see redact.py). The
# block is required; the API key is a secret read from the environment, never
# config.yaml.
_REDACTION: dict = _require("redaction")
REDACTION_ENABLED: bool = bool(_require_in(_REDACTION, "redaction", "enabled"))
REDACTION_ENDPOINT: str = str(_require_in(_REDACTION, "redaction", "endpoint") or "")
_REDACTION_LANGUAGES = _require_in(_REDACTION, "redaction", "languages")
if not isinstance(_REDACTION_LANGUAGES, list) or not _REDACTION_LANGUAGES:
    raise RuntimeError("config.yaml redaction.languages must be a non-empty list")
# Accepted PII languages; the first is the fallback when detection misses.
REDACTION_LANGUAGES: list[str] = [str(x) for x in _REDACTION_LANGUAGES]
REDACTION_LANGUAGE: str = REDACTION_LANGUAGES[0]
